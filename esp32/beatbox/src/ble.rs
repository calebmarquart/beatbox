//! BLE peripheral: advertises, serves one GATT service, and streams
//! raw UART data chunks as notifications.

use bt_hci::controller::ExternalController;
use embassy_futures::join::join;
use embassy_futures::select::select;
use embassy_time::{Duration, Timer};
use esp_hal::peripherals::BT;
use esp_radio::ble::controller::BleConnector;
use trouble_host::prelude::*;

use crate::uart::{UART_DATA, UartPacket};

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
    data: UartPacket,
}

/// Brings up the BLE stack and runs it forever.
pub async fn run(bt: BT<'static>) {
    esp_println::println!("Starting BLE stack...");
    // Ble transport and controller
    let transport = BleConnector::new(bt, Default::default()).unwrap();
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

    let advertise_loop = async {
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

            let Ok(conn) = advertiser.accept().await else {
                continue;
            };
            let Ok(conn) = conn.with_attribute_server(&server) else {
                continue;
            };
            esp_println::println!("BLE connected");

            // Returns when either side finishes (i.e. on disconnect)
            select(
                gatt_events_task(&conn),
                notify_task(&server.stream.data, &conn),
            )
            .await;

            esp_println::println!("BLE disconnected, re-advertising");
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
async fn gatt_events_task<P: PacketPool>(conn: &GattConnection<'_, '_, P>) {
    loop {
        match conn.next().await {
            GattConnectionEvent::Disconnected { reason } => {
                esp_println::println!("disconnect reason: {:?}", reason);
                break;
            }
            GattConnectionEvent::Gatt { event } => {
                if let Ok(reply) = event.accept() {
                    reply.send().await;
                }
            }
            _ => {}
        }
    }
}

/// Forwards queued UART chunks to the connected client as notifications.
async fn notify_task<P: PacketPool>(
    data_char: &Characteristic<UartPacket>,
    conn: &GattConnection<'_, '_, P>,
) {
    loop {
        let packet = UART_DATA.receive().await;
        if data_char.notify(conn, &packet).await.is_err() {
            esp_println::println!("notify failed, dropping connection");
            break;
        }
    }
}
