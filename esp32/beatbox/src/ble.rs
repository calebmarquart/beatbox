//! BLE peripheral: advertises, serves one GATT service, and streams
//! raw UART data chunks as notifications.

use bt_hci::controller::ExternalController;
use embassy_futures::join::join;
use embassy_futures::select::select;
use embassy_time::{Duration, Timer};
use esp_hal::peripherals::BT;
use esp_radio::ble::controller::BleConnector;
use trouble_host::prelude::*;

use crate::uart::{BLE_PACKET_MAX, BlePacket, UART_DATA};

const CONNECTIONS_MAX: usize = 1;
const L2CAP_CHANNELS_MAX: usize = 1;
const DEVICE_NAME: &str = "Beatbox";

#[gatt_server]
struct Server {
    stream: StreamService,
}

#[gatt_service(uuid = "9f1c0001-4b6a-4c1e-9a52-5d3a7b2e0001")]
struct StreamService {
    #[characteristic(uuid = "9f1c0002-4b6a-4c1e-9a52-5d3a7b2e0001", read, notify)]
    data: BlePacket,
}

/// Brings up the BLE stack and runs it forever.
pub async fn run(bt: BT<'static>) {
    esp_println::println!("Starting BLE stack...");
    esp_println::println!("BLE controller init begin");
    let transport = BleConnector::new(bt, Default::default()).unwrap();
    esp_println::println!("BLE controller init complete");
    let ble_controller = ExternalController::<_, 1>::new(transport);

    // BLE MAC address
    let mac_efuse =
        esp_hal::efuse::interface_mac_address(esp_hal::efuse::InterfaceMacAddress::Bluetooth);
    let address = Address::random(core::array::from_fn(|i| mac_efuse.as_bytes()[i]));
    esp_println::println!("BLE MAC address: {:02x?}", address.to_bytes());

    let mut resources: HostResources<DefaultPacketPool, CONNECTIONS_MAX, L2CAP_CHANNELS_MAX> =
        HostResources::new();
    let stack = trouble_host::new(ble_controller, &mut resources).set_random_address(address);

    let Host {
        runner,
        mut peripheral,
        ..
    } = stack.build();

    let server = Server::new_with_config(GapConfig::Peripheral(PeripheralConfig {
        name: DEVICE_NAME,
        appearance: &appearance::UNKNOWN,
    }))
    .unwrap();
    esp_println::println!("BLE host ready; starting runner and advertising");

    let advertise_loop = async {
        let mut connection_id = 0u32;
        loop {
            // Advertise: flags + name (the host finds us by name)
            let mut adv_data = [0u8; 31];
            let len = AdStructure::encode_slice(
                &[
                    AdStructure::Flags(LE_GENERAL_DISCOVERABLE | BR_EDR_NOT_SUPPORTED),
                    AdStructure::CompleteLocalName(DEVICE_NAME.as_bytes()),
                ],
                &mut adv_data[..],
            )
            .unwrap();

            let Ok(advertiser) = peripheral
                .advertise(
                    &Default::default(),
                    Advertisement::ConnectableScannableUndirected {
                        adv_data: &adv_data[..len],
                        scan_data: &[],
                    },
                )
                .await
            else {
                esp_println::println!("advertise failed, retrying");
                Timer::after(Duration::from_millis(500)).await;
                continue;
            };

            let conn = match advertiser.accept().await {
                Ok(conn) => conn,
                Err(error) => {
                    esp_println::println!("BLE connection accept failed: {:?}", error);
                    continue;
                }
            };
            connection_id = connection_id.wrapping_add(1);
            let current_connection_id = connection_id;
            let conn = match conn.with_attribute_server(&server) {
                Ok(conn) => conn,
                Err(error) => {
                    esp_println::println!(
                        "BLE connection {}: GATT server attach failed: {:?}",
                        current_connection_id,
                        error
                    );
                    continue;
                }
            };
            esp_println::println!(
                "BLE connection {} accepted; ATT MTU={}, CCCD handle={:?}",
                current_connection_id,
                conn.raw().att_mtu(),
                server.stream.data.cccd_handle
            );

            // Returns when either side finishes (i.e. on disconnect)
            select(
                gatt_events_task(
                    &conn,
                    server.stream.data.cccd_handle,
                    current_connection_id,
                ),
                notify_task(&server.stream.data, &conn, current_connection_id),
            )
            .await;

            esp_println::println!(
                "BLE connection {} ended; re-advertising",
                current_connection_id
            );
        }
    };

    join(ble_task(runner), advertise_loop).await;
}

/// Drives the BLE host stack. Must run continuously.
async fn ble_task<C: Controller, P: PacketPool>(mut runner: Runner<'_, C, P>) {
    loop {
        if let Err(e) = runner.run().await {
            panic!("BLE runner error: {:?}", e);
        }
    }
}

/// Answers GATT reads/writes (including subscribe requests) until disconnect.
async fn gatt_events_task<P: PacketPool>(
    conn: &GattConnection<'_, '_, P>,
    cccd_handle: Option<u16>,
    connection_id: u32,
) {
    loop {
        match conn.next().await {
            GattConnectionEvent::Disconnected { reason } => {
                esp_println::println!(
                    "BLE connection {} disconnect reason: {:?}",
                    connection_id,
                    reason
                );
                break;
            }
            GattConnectionEvent::Gatt { event } => {
                let cccd_write = match event.payload().incoming() {
                    trouble_host::att::AttClient::Request(
                        trouble_host::att::AttReq::Write { handle, data },
                    )
                    | trouble_host::att::AttClient::Command(
                        trouble_host::att::AttCmd::Write { handle, data },
                    ) if Some(handle) == cccd_handle && data.len() == 2 => {
                        Some([data[0], data[1]])
                    }
                    _ => None,
                };
                match event.accept() {
                    Ok(reply) => {
                        reply.send().await;
                        if let Some(value) = cccd_write {
                            esp_println::println!(
                                "BLE connection {} notification CCCD write accepted: {:02x?}",
                                connection_id,
                                value.as_slice()
                            );
                        }
                    }
                    Err(error) => {
                        esp_println::println!(
                            "BLE connection {} GATT request rejected: {:?}",
                            connection_id,
                            error
                        );
                    }
                }
            }
            _ => {}
        }
    }
}

/// Forwards each queued UART line in MTU-sized notification fragments.
async fn notify_task<P: PacketPool>(
    data_char: &Characteristic<BlePacket>,
    conn: &GattConnection<'_, '_, P>,
    connection_id: u32,
) {
    let mut pending: Option<(crate::uart::UartPacket, usize)> = None;

    'notifications: loop {
        let max_payload = usize::from(conn.raw().att_mtu())
            .saturating_sub(3)
            .min(BLE_PACKET_MAX);
        let mut packet = BlePacket::new();

        while packet.len() < max_payload {
            if pending.is_none() {
                pending = if packet.is_empty() {
                    Some((UART_DATA.receive().await, 0))
                } else {
                    UART_DATA.try_receive().ok().map(|line| (line, 0))
                };
                if pending.is_none() {
                    break;
                }
            }

            let (line, offset) = pending.take().unwrap();
            let count = (line.len() - offset).min(max_payload - packet.len());
            packet
                .extend_from_slice(&line.as_slice()[offset..offset + count])
                .unwrap();

            if offset + count < line.len() {
                pending = Some((line, offset + count));
            }
        }

        // The receiver rebuilds records until LF, so packing may split a line
        // across notifications or include bytes from multiple samples.
        if data_char.notify(conn, &packet).await.is_err() {
            esp_println::println!(
                "BLE connection {} notify failed, dropping connection",
                connection_id
            );
            break 'notifications;
        }
    }
}
