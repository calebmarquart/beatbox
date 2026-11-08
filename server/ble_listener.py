"""Connect to the Beatbox BLE peripheral and print data notifications."""

from __future__ import annotations

import argparse
import asyncio

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

DEFAULT_DEVICE_NAME = "Beatbox"
DATA_CHARACTERISTIC_UUID = "9f1c0002-4b6a-4c1e-9a52-5d3a7b2e0001"


async def listen(device_name: str, characteristic_uuid: str) -> None:
    print(f"Scanning for BLE device {device_name!r}...")
    device = await BleakScanner.find_device_by_name(device_name, timeout=30.0)
    if device is None:
        raise RuntimeError(
            f"Could not find {device_name!r}. Make sure the Beatbox is powered on and advertising."
        )

    print(f"Found {device.name or device_name} ({device.address}); connecting...")

    def on_notification(_sender: BleakGATTCharacteristic, data: bytearray) -> None:
        raw = bytes(data)
        print(f"Notification ({len(raw)} bytes): {raw.hex(' ')}", flush=True)

    async with BleakClient(device) as client:
        print(f"Connected. Subscribing to {characteristic_uuid}...")
        await client.start_notify(characteristic_uuid, on_notification)
        print("Listening for notifications. Press Ctrl+C to stop.")
        while client.is_connected:
            await asyncio.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        default=DEFAULT_DEVICE_NAME,
        help=f"BLE device name (default: {DEFAULT_DEVICE_NAME})",
    )
    parser.add_argument(
        "--characteristic",
        default=DATA_CHARACTERISTIC_UUID,
        help=f"notification characteristic UUID (default: {DATA_CHARACTERISTIC_UUID})",
    )
    args = parser.parse_args()

    try:
        asyncio.run(listen(args.name, args.characteristic))
    except KeyboardInterrupt:
        print("\nStopped listening.")


if __name__ == "__main__":
    main()
