"""Lists available microphone input devices with their index, so you can
pick one for JARVIS_INPUT_DEVICE in .env.

    .venv\\Scripts\\python -m voice.list_devices
"""

from __future__ import annotations

import sounddevice as sd


def main() -> None:
    default_index = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
    print("Input devices (index: name @ default sample rate):\n")
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] <= 0:
            continue
        marker = "  <-- current Windows default" if index == default_index else ""
        print(f"{index:3}: {device['name']} @ {int(device['default_samplerate'])} Hz{marker}")

    print(
        "\nSet JARVIS_INPUT_DEVICE in .env to one of these index numbers "
        "(or a substring of its name), e.g.:\nJARVIS_INPUT_DEVICE=13"
    )


if __name__ == "__main__":
    main()
