#!/usr/bin/env python3
##################################################################################################################################
# Copyright (c) 2025                                                                                          All Rights Reserved
##################################################################################################################################
# CREATION DATE:  07.09.2025
# FILE:           dashboard.py
# DESCRIPTION:    Dashboard for RCT inverter data.
##################################################################################################################################

##################################################################################################################################
# IMPORT MODULES / LIBRARIES                                                                                                     #
##################################################################################################################################
# Standard library modules
import logging
from typing import Any
from datetime import datetime

# Third-party modules
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Local application modules
from rct_client import RctClient

##################################################################################################################################
# MARK: GLOBAL VARIABLES                                                                                                               #
##################################################################################################################################
LOGGER: logging.Logger = logging.getLogger(__name__)
DASHBOARD_REFRESH_INTERVAL_MS: int = 5000


##################################################################################################################################
# MARK: FUNCTION IMPLEMENTATION                                                                                                  #
##################################################################################################################################
def widget_battery_soc(cache: dict[str, tuple[Any, float]]):
    st.header("Battery 🔋")

    # Battery SoC variables
    battery_soc: float | None = None
    timestamp_battery_soc: str | None = None
    battery_soc_raw: tuple[Any, float] | None = cache.get("BATTERY_SOC", None)

    # Battery power variables
    battery_power: float | None = None
    battery_power_raw: tuple[Any, float] | None = cache.get("BATTERY_POWER", None)

    # Get battery SoC and timestamp
    if battery_soc_raw:
        battery_soc = round(battery_soc_raw[0] * 100, 2)
        timestamp_battery_soc = datetime.fromtimestamp(battery_soc_raw[1]).strftime("%H:%M:%S")

    # Get battery power and timestamp
    if battery_power_raw:
        battery_power = round(battery_power_raw[0] / 1000, 2)

    if "initial_battery_soc" not in st.session_state and battery_soc is not None:
        st.session_state["initial_battery_soc"] = battery_soc

    if "initial_battery_power" not in st.session_state and battery_power is not None:
        st.session_state["initial_battery_power"] = battery_power

    if (
        "initial_battery_soc" in st.session_state
        and battery_soc is not None
        and "initial_battery_power" in st.session_state
        and battery_power is not None
    ):
        if "battery_soc_values" not in st.session_state:
            st.session_state["battery_soc_values"] = []

        if "battery_power_values" not in st.session_state:
            st.session_state["battery_power_values"] = []

        st.session_state["battery_soc_values"].append(battery_soc)
        st.session_state["battery_power_values"].append(battery_power)
        st.metric(
            label="Battery State of Charge",
            value=f"{battery_soc} %",
            delta=f"{-battery_power} kW",
            chart_data=st.session_state["battery_soc_values"],
            chart_type="line",
            border=True,
        )
        if timestamp_battery_soc:
            st.markdown(f"Last Update: **{timestamp_battery_soc}**")
        st.badge(label=str(max(st.session_state["battery_soc_values"])), icon="⬆️", color="green")
        st.badge(label=str(min(st.session_state["battery_soc_values"])), icon="⬇️", color="red")


def widget_household_load(cache: dict[str, tuple[Any, float]]):
    st.header("Household Load 🏠")
    internal_household_load_power_kw: float | None = None
    timestamp_internal_household_load_power: str | None = None
    internal_household_load_power_raw: tuple[Any, float] | None = cache.get("HOUSEHOLD_LOAD_INTERNAL", None)

    # Convert raw value [W] to [kW] and round to 2 decimals
    if internal_household_load_power_raw:
        internal_household_load_power_kw = round((internal_household_load_power_raw[0] / 1000), 2)
        timestamp_internal_household_load_power = datetime.fromtimestamp(internal_household_load_power_raw[1]).strftime(
            "%H:%M:%S"
        )

    if "initial_internal_household_load_power_kw" not in st.session_state and internal_household_load_power_kw is not None:
        st.session_state["initial_internal_household_load_power_kw"] = internal_household_load_power_kw

    if "initial_internal_household_load_power_kw" in st.session_state and internal_household_load_power_kw is not None:
        if "internal_household_load_power_values" not in st.session_state:
            st.session_state["internal_household_load_power_values"] = []

        st.session_state["internal_household_load_power_values"].append(internal_household_load_power_kw)

        st.metric(
            label="Internal Household Load",
            value=f"{internal_household_load_power_kw} kW",
            chart_data=st.session_state["internal_household_load_power_values"],
            chart_type="line",
            border=True,
        )


def widget_solar_generators(cache: dict[str, tuple[Any, float]]):
    st.header("Solar Generators 🔆")
    solar_gen_power: float | None = None
    timestamp_solar_gen_power: str | None = None
    solar_gen_a_power_raw: tuple[Any, float] | None = cache.get("SOLAR_GENERATOR_A_POWER", None)
    solar_gen_b_power_raw: tuple[Any, float] | None = cache.get("SOLAR_GENERATOR_B_POWER", None)

    if solar_gen_a_power_raw and solar_gen_b_power_raw:
        solar_gen_power = round((solar_gen_a_power_raw[0] + solar_gen_b_power_raw[0]) / 1000, 2)
        timestamp_solar_gen_power = datetime.fromtimestamp(min(solar_gen_a_power_raw[1], solar_gen_b_power_raw[1])).strftime(
            "%H:%M:%S"
        )

    if "initial_solar_gen_power" not in st.session_state and solar_gen_power is not None:
        st.session_state["initial_solar_gen_power"] = solar_gen_power

    if "initial_solar_gen_power" in st.session_state and solar_gen_power is not None:
        if "solar_gen_power_values" not in st.session_state:
            st.session_state["solar_gen_power_values"] = []

        st.session_state["solar_gen_power_values"].append(solar_gen_power)
        st.metric(
            label="Solar Generator Power",
            value=f"{solar_gen_power} kW",
            border=True,
        )
        if timestamp_solar_gen_power:
            st.markdown(f"Last Update: **{timestamp_solar_gen_power}**")
        st.badge(label=str(max(st.session_state["solar_gen_power_values"])), icon="⬆️", color="green")
        st.badge(label=str(min(st.session_state["solar_gen_power_values"])), icon="⬇️", color="red")

        st.subheader("Solar Genaration Power Values")
        st.line_chart(st.session_state["solar_gen_power_values"], x_label="Refresh Cycles 🔁", y_label="kW ⚡ ")


##################################################################################################################################
# MARK: SCRIPT IMPLEMENTATION                                                                                                    #
##################################################################################################################################
if __name__ == "__main__":
    logging.basicConfig(
        filename="dashboard.log", level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    refresh_counter: int = st_autorefresh(interval=DASHBOARD_REFRESH_INTERVAL_MS)
    st.set_page_config(page_title="RCT Dashboard", page_icon="☀️", layout="wide")

    if "rct_client" not in st.session_state:
        st.session_state["rct_client"] = RctClient()
        st.session_state["rct_client"].connect()
        st.session_state["oid_keys"] = [
            "BATTERY_SOC",
            "BATTERY_POWER",
            "SOLAR_GENERATOR_A_POWER",
            "SOLAR_GENERATOR_B_POWER",
            "HOUSEHOLD_LOAD_INTERNAL",
            "GRID_FEED_YEAR_SUM",
            "BATTERY_CURRENT",
        ]
        st.session_state["rct_client"].start_polling(keys=st.session_state["oid_keys"])

    cache: dict[str, tuple[Any, float]] = st.session_state["rct_client"].get_cache()

    st.set_page_config(layout="wide")
    st.markdown("<h1 style='text-align: center'>RCT Dashboard ⚡</h1>", unsafe_allow_html=True)
    st.markdown(f"**Current Time: {datetime.now().strftime('%H:%M:%S')}**")

    col1, col2, col3 = st.columns(3)

    with col1:
        widget_battery_soc(cache=cache)

    with col2:
        widget_household_load(cache=cache)

    with col3:
        widget_solar_generators(cache=cache)
