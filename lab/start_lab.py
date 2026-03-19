from pathlib import Path

from .mock_switch import MockSwitch, SwitchState


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    switches = [
        MockSwitch(
            "0.0.0.0",
            2222,
            SwitchState.from_json(base_dir / "switch_configs" / "switch_core.json"),
        ),
        MockSwitch(
            "0.0.0.0",
            2223,
            SwitchState.from_json(base_dir / "switch_configs" / "switch_access.json"),
        ),
        MockSwitch(
            "0.0.0.0",
            2224,
            SwitchState.from_json(base_dir / "switch_configs" / "switch_legacy.json"),
        ),
    ]
    for switch in switches:
        switch.start()
    try:
        input("Mock lab running. Press Enter to stop.\n")
    except EOFError:
        import time

        while True:
            time.sleep(5)


if __name__ == "__main__":
    main()
