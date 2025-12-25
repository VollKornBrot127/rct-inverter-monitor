# RCT Inverter Monitor ☀️

## Description

This project is a Python application that reads data from RCT power inverters via TCP.
It is based on the open-source Python package [`rctclient`](https://github.com/svalouch/python-rctclient), which implements the underlying communication protocol.

---

## Disclaimer

This software is provided "as is", without warranty of any kind, express or implied. The author assumes no responsibility or liability for any damages, data loss, malfunctions, incorrect readings, or other issues arising from the use of this software.

Use this software at your own risk.

This software interacts with external hardware.
Improper use may affect the operation of your inverter or connected systems.

### No Affiliation

This project is not affiliated with, endorsed by, or supported by RCT Power GmbH.
RCT is a registered trademark of its respective owner.

### Third-Party Software

This project uses the open-source Python package [`rctclient`](https://github.com/svalouch/python-rctclient).
The author of this project is not the author or maintainer of [`rctclient`](https://github.com/svalouch/python-rctclient) and is not affiliated with its developers.

### Support

This is a private open-source project.
There is no guarantee of support, maintenance, or continued development.

---

## Usage

This project is not published on PyPI.
To use it, you must install it directly from the Git repository.

### Installation using `uv`

```Bash
uv add git+https://github.com/VollKornBrot127/rct-inverter-monitor --branch main
```

### Installation using `pip`

```Bash
pip install git+https://github.com/VollKornBrot127/rct-inverter-monitor@main
```

### Using the package in your code

After installation, you can import the package in your Python code:

```Python
from rct_inverter_monitor import RctInverterMonitor
```

A simple program that continuously polls and displays the battery SoC (state of charge) and the internal household load every 5 seconds could look like this:

```Python
import time
from rct_inverter_monitor import RctInverterMonitor

rct_monitor = RctInverterMonitor()
rct_monitor.connect()

try:
    rct_monitor.start_polling(keys=["BATTERY_SOC", "HOUSEHOLD_LOAD_INTERNAL"], interval=5.0)

    while True:
        print(rct_monitor.get_cache())
        time.sleep(5.0)
except KeyboardInterrupt:
    rct_monitor.stop_polling()
finally:
    rct_monitor.close()
```

The available keys can be viewed [here](https://github.com/VollKornBrot127/rct-inverter-monitor/blob/main/src/rct_inverter_monitor/oid_mapping.yml).

Please note that errors may occasionally appear in the log (e.g., "CRC mismatch" or "Frame error while consuming incoming data frame"). These are unavoidable, as the RCT inverter does not always provide clean or the requested data. For more information, please refer to the [documentation for the `rctclient` package](https://rctclient.readthedocs.io/en/latest/usage.html#encoding-and-decoding-data).
