"""Updates the saved data json schema."""

import logging

def v1_blank():
    return dict()

def v2_blank():
    return {
        "version": 2,
        "whitelist": [],
        "params": {}
    }

def v1_to_v2(v1_data:dict) -> dict:
    """v1 schema only had no version number, and only contained the parameters.
    v2 separates parameters from whitelist, and includes the version number."""
    logging.debug("Updating schema from v1 to v2")
    new_data = {
        "version": 2,
        "whitelist": [],
        "params": v1_data
    }
    return new_data

def get_blank_schema(version:int):
    match version:
        case 1:
            return v1_blank()
        case 2:
            return v2_blank()

def to_latest(data:dict, current_version:int):
    logging.info("Updating outdated saved data schema")
    if current_version == 1:
        data = v1_to_v2(data)
        current_version += 1

    # if current_version == 2:
    #     data = v2_to_v3(data)
    #     current_version += 1

    return data
    