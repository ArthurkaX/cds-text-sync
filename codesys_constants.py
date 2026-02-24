# -*- coding: utf-8 -*-
"""
codesys_constants.py - Shared constants for CODESYS scripts

Contains all CODESYS object type GUIDs, exportable types, and other
constants used across multiple scripts.
"""

# Object type GUIDs for reference
TYPE_GUIDS = {
    "pou": "6f9dac99-8de1-4efc-8465-68ac443b7d08",           # PROGRAM, FUNCTION, FUNCTION_BLOCK
    "gvl": "ffbfa93a-b94d-45fc-a329-229860183b1d",           # Global Variable List
    "dut": "2db5746d-d284-4425-9f7f-2663a34b0ebc",           # Data Types (STRUCT, ENUM, etc.)
    "action": "8ac092e5-3128-4e26-9e7e-11016c6684f2",        # Action
    "method": "f8a58466-d7f6-439f-bbb8-d4600e41d099",        # Method
    "property": "5a3b8626-d3e9-4f37-98b5-66420063d91e",      # Property
    "property_accessor": "792f2eb6-721e-4e64-ba20-bc98351056db", # Property Get/Set
    "folder": "738bea1e-99bb-4f04-90bb-a7a567e74e3a",        # Folder
    "device": "225bfe47-7336-4dbc-9419-4105a7c831fa",        # Device
    "plc_logic": "40b404f9-e5dc-42c6-907f-c89f4a517386",     # Plc Logic
    "application": "639b491f-5557-464c-af91-1471bac9f549",   # Application
    "library_manager": "adb5cb65-8e1d-4a00-b70a-375ea27582f3", # Library Manager
    "task_config": "ae1de277-a207-4a28-9efb-456c06bd52f3",   # Task Configuration
    "task": "98a2708a-9b18-4f31-82ed-a1465b24fa2d",          # Task
    "itf": "54ce33d2-c430-4eb6-a66f-1f0624d7705b",           # Interface
    "nvl_sender": "ffb96994-3252-4467-8507-6a1883584989",    # Network Variable List (Sender)
    "nvl_receiver": "ea9e7828-b80c-4ec7-9f68-52210f019623",  # Network Variable List (Receiver)
    "param_list": "f89f7675-27f3-455b-b98a-243e8673a5a8",    # Parameter List
    "persistent_gvl": "3183921b-cc91-4712-9781-c3b6555122b5",# Persistent GVL
    "recipe_manager": "47225134-2e90-48e0-a42e-9ed7cf91c010",# Recipe Manager
    "recipe": "3e9a7218-1e43-4f9e-a0e2-656f4d36e8b4",         # Recipe
    "visu": "f18bec89-9fef-401d-9953-2f11739a6808",           # Visualization
    "textlist": "2bef0454-1bd3-412a-ac2c-af0f31dbc40f",      # Text List (updated from discovery)
    "global_text_list": "63784cbb-9ba0-45e6-9d69-babf3f040511", # Global Text List
    "imagepool": "6507a8fd-035f-464a-bd5b-7f15e8ac084a",     # Image Pool
    "visu_manager": "4d3fdb8f-ab50-4c35-9d3a-d4bb9bb9a628",  # Visualization Manager
    "web_visu": "0fdbf158-1ae0-47d9-9269-cd84be308e9d",      # WebVisu
    "alarm_config": "c0a56ce5-14a3-4757-ac56-3eab44c974b3",  # Alarm Configuration
    "alarm_group": "413e2a7d-adb1-4d2c-be29-6ae6e4fab820",   # Alarm Group/Object
    "task_call": "6f9da924-d2e2-4467-9c9e-5e26bc1c1111",     # Task Call
    "symbol_config": "21d4fe94-4123-4e23-9091-ead220afbd1f", # Symbol Configuration
    "target_visu": "bc63f5fa-d286-4786-994e-7b27e4f97bd5",   # Target Visualization
    "image": "9001d745-b9c5-4d77-90b7-b29c3f77a23b",         # Image entry in ImagePool
    "alarm_storage": "5bd56248-46fc-4108-be33-ed01ad87d070", # Alarm Storage
    "trace": "f7aa3620-8073-4c91-b6ec-86ed9eb60303",         # Trace
    "project_info": "085afe48-c5d8-4ea5-ab0d-b35701fa6009",  # Project Information
    "type_f18": "f18bec89-9fef-401d-9953-2f11739a6808",      # Unknown (Visualization?)
    "type_21f": "21f4ed1d-ec95-4666-820e-4abf64d93d6b",      # Unknown (Infeed/ER related)
    "type_085": "085766fd-043e-4545-8e8d-d651d56d5d3b",      # Unknown (Hardware/PM_E)
    "file_object": "a56744ff-693f-4597-95f9-0e1c529fffc2",   # External files/scripts
    "alarm_class": "b8b46f61-c7c1-4259-87e4-26fe674798f9",   # Alarm Class (Error, Warning, etc.)
    "imagepool_variant": "bb0b9044-714e-4614-ad3e-33cbdf34d16b", # Alternative ImagePool GUID
    "unit_conversion": "3662d04a-384c-4734-9189-9e8756910793", # Unit Conversion
    "softmotion_pool": "e9159722-55bc-49e5-8034-fbd278ef718f", # SoftMotion Axis Pool
    "visu_style": "8e687a04-7ca7-42d3-be06-fcbda676c5ef",    # Visualization Style
    "task_local_gvl": "c2cda7a9-0ba4-4146-b563-22a42fa0eb72", # Task Local GVL (GVL attached to task)
    "project_settings": "8753fe6f-4a22-4320-8103-e553c4fc8e04", # Project Settings
}

# Types that contain exportable ST code
EXPORTABLE_TYPES = [
    TYPE_GUIDS["pou"],
    TYPE_GUIDS["gvl"],
    TYPE_GUIDS["dut"],
    TYPE_GUIDS["itf"],
    TYPE_GUIDS["nvl_sender"],
    TYPE_GUIDS["nvl_receiver"],
    TYPE_GUIDS["param_list"],
    TYPE_GUIDS["textlist"],
    TYPE_GUIDS["global_text_list"],
    TYPE_GUIDS["symbol_config"],
    TYPE_GUIDS["imagepool"],
    TYPE_GUIDS["unit_conversion"],
    TYPE_GUIDS["visu"],            # Authorization for Visualization export
    TYPE_GUIDS["visu_manager"],
    # web_visu and target_visu are NOT listed here — they are children of
    # visu_manager and exported as part of its recursive XML export.
    TYPE_GUIDS["alarm_config"],
    TYPE_GUIDS["alarm_group"],
    TYPE_GUIDS["alarm_storage"],
    TYPE_GUIDS["task_config"],
    TYPE_GUIDS["task"],
    TYPE_GUIDS["library_manager"],
    TYPE_GUIDS["trace"],
    TYPE_GUIDS["softmotion_pool"],
    TYPE_GUIDS["visu_style"],
    TYPE_GUIDS["project_settings"],
    TYPE_GUIDS["device"],
    TYPE_GUIDS["file_object"],
    TYPE_GUIDS["alarm_class"],
    TYPE_GUIDS["imagepool_variant"],
    TYPE_GUIDS["type_21f"],        # Unknown type (46 count)
    TYPE_GUIDS["type_085"],        # Device modules
    TYPE_GUIDS["action"],
    TYPE_GUIDS["method"],
    TYPE_GUIDS["property"],
    TYPE_GUIDS["property_accessor"],
    TYPE_GUIDS["task_local_gvl"],  # Task Local GVL - same structure as regular GVL
]

# Types that should be exported as native XML
XML_TYPES = [
    TYPE_GUIDS["visu"],
    TYPE_GUIDS["textlist"],
    TYPE_GUIDS["global_text_list"],
    TYPE_GUIDS["imagepool"],
    TYPE_GUIDS["symbol_config"],
    TYPE_GUIDS["alarm_config"],
    TYPE_GUIDS["alarm_group"],
    TYPE_GUIDS["alarm_storage"],
    TYPE_GUIDS["visu_manager"],
    # web_visu and target_visu are part of visu_manager's recursive export
    TYPE_GUIDS["task_config"],
    TYPE_GUIDS["task"],
    TYPE_GUIDS["library_manager"],
    TYPE_GUIDS["trace"],
    TYPE_GUIDS["softmotion_pool"],
    TYPE_GUIDS["visu_style"],
    TYPE_GUIDS["project_settings"],
    TYPE_GUIDS["device"],
    TYPE_GUIDS["type_085"],
    TYPE_GUIDS["file_object"],
    TYPE_GUIDS["alarm_class"],
    TYPE_GUIDS["imagepool_variant"],
    TYPE_GUIDS["type_21f"],
    TYPE_GUIDS["task_local_gvl"],
    TYPE_GUIDS["nvl_sender"],
    TYPE_GUIDS["nvl_receiver"],
]

# Implementation section marker used in ST files
IMPL_MARKER = "// === IMPLEMENTATION ==="

# Property accessor markers for combined property files
PROPERTY_GET_MARKER = "// === GET ==="
PROPERTY_SET_MARKER = "// === SET ==="

# Default sync timeout in milliseconds
DEFAULT_TIMEOUT_MS = 10000

# Characters forbidden in filenames
FORBIDDEN_CHARS = ["<", ">", ":", "\"", "/", "\\", "|", "?", "*"]

# Files that should be ignored by the sync engine
RESERVED_FILES = {
    "_metadata.json", "_config.json", "_metadata.csv", "BASE_DIR",
    "sync_debug.log", "compare.log", ".project", ".gitattributes",
    ".gitignore"
}

# Reverse mapping for human-readable type names
TYPE_NAMES = {v: k for k, v in TYPE_GUIDS.items()}
