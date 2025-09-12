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
from typing import Any, Optional
from datetime import datetime

# Third-party modules
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Local application modules
from rct_client import RctClient

##################################################################################################################################
# GLOBAL VARIABLES                                                                                                               #
##################################################################################################################################

##################################################################################################################################
# CLASS IMPLEMENTATION                                                                                                           #
##################################################################################################################################

##################################################################################################################################
# FUNCTION IMPLEMENTATION                                                                                                        #
##################################################################################################################################

##################################################################################################################################
# SCRIPT IMPLEMENTATION                                                                                                          #
##################################################################################################################################
if __name__ == "__main__":

    i_refresh_counter: int = st_autorefresh(interval=2000)

    if "rct_client" not in st.session_state:
        st.session_state["rct_client"] = RctClient()
        st.session_state["rct_client"].connect()
        st.session_state["oid_keys"] = ["BATTERY_SOC", "BATTERY_POWER", "SOLAR_GENERATOR_A_POWER", "SOLAR_GENERATOR_B_POWER"]
        st.session_state["rct_client"].start_polling(l_keys=st.session_state["oid_keys"])

    d_cache: dict[str, tuple[Any, float]] = st.session_state["rct_client"].get_cache()

    st.set_page_config(layout="wide")
    # st.title("_RCT Dashboard_ ⚡")
    st.markdown("<h1 style='text-align: center'>RCT Dashboard ⚡</h1>", unsafe_allow_html=True)
    st.markdown(f"**Current Time:** `{datetime.now().strftime("%H:%M:%S")}`")

    o_col1, o_col2, o_col3 = st.columns(3)

    with o_col1:
        st.header("Battery 🔋")

        # Battery SoC variables
        f_battery_soc: Optional[float] = None
        s_timestamp_battery_soc: Optional[str] = None
        f_battery_soc_raw: Optional[tuple[Any, float]] = d_cache.get("BATTERY_SOC", None)

        # Battery power variables
        f_battery_power: Optional[float] = None
        s_timestamp_battery_power: Optional[str] = None
        f_battery_power_raw: Optional[tuple[Any, float]] = d_cache.get("BATTERY_POWER", None)

        # Get battery SoC and timestamp
        if f_battery_soc_raw:
            f_battery_soc = round(f_battery_soc_raw[0] * 100, 2)
            s_timestamp_battery_soc = datetime.fromtimestamp(f_battery_soc_raw[1]).strftime("%H:%M:%S")

        # Get battery power and timestamp
        if f_battery_power_raw:
            f_battery_power = round(f_battery_power_raw[0] / 1000, 2)
            s_timestamp_battery_power = datetime.fromtimestamp(f_battery_power_raw[1]).strftime("%H:%M:%S")

        if "initial_battery_soc" not in st.session_state and f_battery_soc is not None:
            st.session_state["initial_battery_soc"] = f_battery_soc

        if "initial_battery_power" not in st.session_state and f_battery_power is not None:
            st.session_state["initial_battery_power"] = f_battery_power

        if (
            "initial_battery_soc" in st.session_state
            and f_battery_soc is not None
            and "initial_battery_power" in st.session_state
            and f_battery_power is not None
        ):
            if "battery_soc_values" not in st.session_state:
                st.session_state["battery_soc_values"] = []

            if "battery_power_values" not in st.session_state:
                st.session_state["battery_power_values"] = []

            st.session_state["battery_soc_values"].append(f_battery_soc)
            st.session_state["battery_power_values"].append(f_battery_power)
            st.metric(
                label="Battery State of Charge",
                value=f"{f_battery_soc} %",
                delta=f"{-f_battery_power} kW",
                chart_data=st.session_state["battery_soc_values"],
                chart_type="line",
                border=True,
            )
            if s_timestamp_battery_soc:
                st.markdown(f"Last updated: `{s_timestamp_battery_soc}`")
            st.markdown(f"Max Battery SoC: `{max(st.session_state["battery_soc_values"])} %`")
            st.markdown(f"Min Battery SoC: `{min(st.session_state["battery_soc_values"])} %`")

            st.line_chart(st.session_state["battery_soc_values"], x_label="Refresh Cycles 🔁", y_label="State of Charge [%] 🔋")

    with o_col2:
        st.header("Household Load 🏠")

    with o_col3:
        st.header("Solar Generators 🔆")
        f_solar_gen_power: Optional[float] = None
        s_timestamp_solar_gen_power: Optional[str] = None
        f_solar_gen_a_power_raw: Optional[tuple[Any, float]] = d_cache.get("SOLAR_GENERATOR_A_POWER", None)
        f_solar_gen_b_power_raw: Optional[tuple[Any, float]] = d_cache.get("SOLAR_GENERATOR_B_POWER", None)

        if f_solar_gen_a_power_raw and f_solar_gen_b_power_raw:
            f_solar_gen_power = round((f_solar_gen_a_power_raw[0] + f_solar_gen_b_power_raw[0]) / 1000, 2)
            s_timestamp_solar_gen_power = datetime.fromtimestamp(
                min(f_solar_gen_a_power_raw[1], f_solar_gen_b_power_raw[1])
            ).strftime("%H:%M:%S")

        if "initial_solar_gen_power" not in st.session_state and f_solar_gen_power is not None:
            st.session_state["initial_solar_gen_power"] = f_solar_gen_power

        if "initial_solar_gen_power" in st.session_state and f_solar_gen_power is not None:
            if "solar_gen_power_values" not in st.session_state:
                st.session_state["solar_gen_power_values"] = []

            st.session_state["solar_gen_power_values"].append(f_solar_gen_power)
            st.metric(
                label="Solar Generator Power",
                value=f"{f_solar_gen_power} kW",
                delta=f"{round(f_solar_gen_power - st.session_state['initial_solar_gen_power'], 2)} kW",
                border=True,
            )
            if s_timestamp_solar_gen_power:
                st.markdown(f"Last updated: `{s_timestamp_solar_gen_power}`")
            st.markdown(f"Max Power: `{max(st.session_state["solar_gen_power_values"])} kW`")
            st.markdown(f"Min Power: `{min(st.session_state["solar_gen_power_values"])} kW`")

            st.subheader("Solar Genaration Power Values")
            st.area_chart(st.session_state["solar_gen_power_values"], x_label="Refresh Cycles 🔁", y_label="kW ⚡ ")
