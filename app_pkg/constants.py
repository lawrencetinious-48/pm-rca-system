"""
Constants and configuration values for the PM/RCA System.
"""

# Alert and SLA constants
_ALERT_COOLDOWN = 1800
_SLA_SCAN_COOLDOWN = 300
_SLA_DUE_SOON_ALERT_COOLDOWN_HOURS = 6
_SLA_OVERDUE_ESCALATION_COOLDOWN_HOURS = 3
HIGH_RISK_THRESHOLD = 70
MEDIUM_RISK_THRESHOLD = 40
SLA_DUE_SOON_HOURS = 6
SLA_HOURS_CRITICAL = 24
SLA_HOURS_STANDARD = 48

# Image magic bytes
_IMAGE_MAGIC = (
    (b'\x89PNG\r\n\x1a\n', 'png'),
    (b'\xff\xd8\xff',       'jpeg'),
    (b'GIF87a',             'gif'),
    (b'GIF89a',             'gif'),
)

# Role definitions
ADMIN_ROLES = {"manager", "general_manager", "developer"}
DESK_ROLES = {"staff", "manager", "general_manager", "developer"}
TECHNICIAN_ROLES = {"technician"}
VALID_ACCOUNT_ROLES = ("developer", "general_manager", "manager", "staff", "technician")
ROLE_EQUIVALENTS = {
    "desk_staff": "staff",
}
LOGIN_MATRIX_KEYS = ("developer", "staff", "technician")
DEFAULT_ROLE_ACCESS_MATRIX = {
    "developer": ["developer"],
    "staff": ["staff", "manager", "general_manager"],
    "technician": ["technician"],
}

# Dashboard menu configuration
ROLE_DASHBOARD_MENU = {
    "developer":[
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "User Management", "endpoint": "developer_user_control"},
        {"label": "Security Posture", "endpoint": "developer_security_posture"},
        {"label": "Photo Library", "endpoint": "developer_photo_library"},
        {"label": "Share Login URL", "endpoint": "system_share_url"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "staff": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Desk Activities", "endpoint": "desk_activities"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "manager": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Desk Activities", "endpoint": "desk_activities"},
        {"label": "Approvals", "endpoint": "desk_activities"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "general_manager": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Desk Activities", "endpoint": "desk_activities"},
        {"label": "Approvals", "endpoint": "desk_activities"},
        {"label": "User Overview", "endpoint": "admin_staff"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "technician": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Field RCA", "endpoint": "field_rca"},
        {"label": "My Submissions", "endpoint": "technician_submissions"},
        {"label": "Rejected Reports", "endpoint": "technician_rejected_reports"},
        {"label": "Calendar", "endpoint": "technician_calendar"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
}

# Avatar options
AVATAR_OPTIONS = (
    {"key": "technician",  "label": "Technician",           "icon": "person-fill-gear",      "gender": "male"},
    {"key": "male_exec",   "label": "Male Office",   "icon": "person-badge-fill",     "gender": "male"},
    {"key": "female_exec", "label": "Female Office", "icon": "person-vcard-fill",     "gender": "female"},
    {"key": "developer",   "label": "Admin",                "icon": "person-workspace",      "gender": "other"},
    {"key": "neutral",     "label": "Default",              "icon": "person-circle",         "gender": "other"},
)
AVATAR_ICON_MAP = {option["key"]: option["icon"] for option in AVATAR_OPTIONS}
AVATAR_KEYS = set(AVATAR_ICON_MAP.keys())

# Supported languages
SUPPORTED_LANGUAGES = {
    "en": {"name": "English", "dir": "ltr"},
    "sw": {"name": "Swahili", "dir": "ltr"},
    "fr": {"name": "French", "dir": "ltr"},
    "ar": {"name": "Arabic", "dir": "rtl"},
}

# Settings translations
SETTINGS_TRANSLATIONS = {
    "en": {
        "settings_title": "System Settings",
        "language": "Language",
        "language_help": "Choose your preferred display language.",
        "choose_language": "Choose language",
        "appearance": "Appearance",
        "appearance_help": "Switch between light mode and dark mode.",
        "dark_mode": "Dark mode",
        "apply_theme": "Apply Theme",
        "related_pages": "Related Pages",
    },
    "sw": {
        "settings_title": "Mipangilio ya Mfumo",
        "language": "Lugha",
        "language_help": "Chagua lugha unayopendelea kwenye mfumo.",
        "choose_language": "Chagua lugha",
        "appearance": "Muonekano",
        "appearance_help": "Badilisha kati ya hali ya mwanga na hali ya giza.",
        "dark_mode": "Hali ya giza",
        "apply_theme": "Tumia Muonekano",
        "related_pages": "Kurasa Zinazohusiana",
    },
    "fr": {
        "settings_title": "Parametres du systeme",
        "language": "Langue",
        "language_help": "Choisissez votre langue d'affichage preferee.",
        "choose_language": "Choisir la langue",
        "appearance": "Apparence",
        "appearance_help": "Basculer entre le mode clair et le mode sombre.",
        "dark_mode": "Mode sombre",
        "apply_theme": "Appliquer le theme",
        "related_pages": "Pages associees",
    },
    "ar": {
        "settings_title": "إعدادات النظام",
        "language": "اللغة",
        "language_help": "اختر لغة العرض المفضلة لديك.",
        "choose_language": "اختر اللغة",
        "appearance": "المظهر",
        "appearance_help": "التبديل بين الوضع الفاتح والوضع الداكن.",
        "dark_mode": "الوضع الداكن",
        "apply_theme": "تطبيق المظهر",
        "related_pages": "صفحات ذات صلة",
    },
}

# Technician PM Sections
TECHNICIAN_PM_SECTIONS = [
    {
        "title": "ATTRIBUTE",
        "fields": [
            "Activity", "Activity Date", "Activity Time", "Access Ref", "Site Number", "Site Name",
            "Site Type", "Purpose of Visit", "Confirm Personal Protective Equipment", "Site Clean",
            "Security Guard Present?", "Comment"
        ]
    },
    {
        "title": "GENERATOR CHECKS",
        "fields": [
            "Number of fuel Tanks", "Tank Type (Base/ Standalone)", "Diesel Tank Capacity (L)",
            "Diesel level (L)", "Is fuel sensor connected?", "Is fuel sensor functional?",
            "DG Manufacturer", "DG Serial Number", "DG Engine Serial Number", "DG Capacity (kVA)",
            "DG Hour Service Kit", "Date of Last Service", "DG Run Hour at Last Service",
            "Current DG Run Hours", "DG Battery on Site", "Is Battery on DG Working?",
            "Is DG oil filter replaced?", "Is DG fuel filter replaced?", "Is DG air filter replaced?",
            "Liters of Engine Oil Used", "Any Engine Oil Topped up other than DG Service Oil in Liters",
            "Signs of leakage along the DG fuel supply line", "If yes, has the leak been fixed?",
            "Is DG Fan Belt in good condition", "Has Coolant Been Added?", "Amount of Coolant Added in Liters",
            "DG Controller Manufacturer", "DG Controller Serial Number", "DG Controller Model Number",
            "Is controller in Auto mode?"
        ]
    },
    {
        "title": "ATS/ AUTOMATION CHECKS",
        "fields": [
            "ATS Installed?", "Is ATS Working?", "Has ATS functionality been tested by simulating a mains failure",
            "Is Site Connected to Grid?", "Was grid available during site visit?", "Any grid faults identified? Share.",
            "Meter Type (Post/ pre-paid)", "Grid Meter Number", "Grid Meter Reading", "Is Grid Meter Working?",
            "Connection Type: (Single or Three Phase)", "Grid supply current - Ph3 (A)"
        ]
    },
    {
        "title": "DC SYSTEMS: RECTIFIER CHECKS",
        "fields": [
            "Number of Rectifiers Installed", "DC Location: (Indoor/ Outdoor)", "Rectifier Type",
            "Rectifier Serial Number", "Rectifier Model Number", "DC Loads (A)", "Rectifier Module Capacity",
            "System Voltage", "No of slots available in the rectifier", "Are rectifier modules cleared of dust?",
            "No. of Rectifiers Modules Present", "No of Working Rectifier Modules", "No. of Faulty Rectifier Modules"
        ]
    },
    {
        "title": "DC SYSTEMS: BATTERY CHECKS",
        "fields": [
            "Are Batteries Installed?", "Battery Bank Location (Indoor /outdoor)", "Battery Manufacturer",
            "Battery Capacity", "Number of Battery strings", "Battery Condition", "Number of batteries per strings in the Bank",
            "Total Number of Batteries at site", "Number of Battery Strings Connected", "Approximate Battery Backup Time",
            "Is Hybrid Installed?", "Type of Hybrid Installed", "Is Hybrid Working?", "Hybrid parameters checked?",
            "Is battery current limit set?", "Are all alarms wires connected?", "Is battery capacity set as per installed battery?",
            "Ensure all terminations and connections are tightened"
        ]
    },
    {
        "title": "EARTHING CHECKS",
        "fields": [
            "Earthing Resistance - Generator", "Earthing Resistance - ATS", "Earthing Resistance - ACDB",
            "Earthing Resistance - Rectifier", "Earthing Resistance - DCDB", "Earthing Resistance - RMS Unit",
            "Earthing Resistance - Tenant Equipment", "Earthing Resistance - Tower Leg", "Earthing Resistance - Fence"
        ]
    },
    {
        "title": "EXTERNAL ALARMS CHECKS",
        "fields": ["Are External Alarms connected", "Have Alarms been tested with NOC?"]
    },
    {
        "title": "SHELTER STATUS",
        "fields": [
            "No of Shelter Number", "Visible signs of leakage", "Openings/gaps in walls or roof",
            "If yes, seal all openings in wall with approvals", "No of  Aircons in Shelter",
            "Are all Aircons in Shelter Functional", "Door Status", "Floor Status", "Roof Status",
            "Are all Shelter Lighting Working?"
        ]
    },
    {
        "title": "SITE CLOSURE AFTER WORKS",
        "fields": [
            "Have you logged out with Airtel NOC", "Is Gate Closed on Exit",
            "Is gate not closed because someone else is on site?"
        ]
    }
]

# Technician Photo Fields
TECHNICIAN_PHOTO_FIELDS = [
    {"key": "site_signage_board", "label": "Site Signage Board"},
    {"key": "dg_closed_doors", "label": "Full view of DG Appearance, Closed doors"},
    {"key": "dg_open_doors", "label": "Full view DG Photo when Canopy doors open"},
    {"key": "dg_run_hours_photo", "label": "DG Run Hours Photo"},
    {"key": "dg_serial_number_photo", "label": "DG Serial Number Photo"},
    {"key": "clamped_ac_loads_photo", "label": "Clamped AC Loads Photo"},
    {"key": "starter_battery_photo", "label": "Starter Battery Photo"},
    {"key": "dg_engine_serial_number_photo", "label": "DG Engine Serial Number Photo"},
    {"key": "dg_battery_voltage_photo", "label": "DG battery Voltage Photo (When AC power off)"},
    {"key": "fixed_fan_belt_photo", "label": "Fixed Fan Belt Photo"},
    {"key": "old_fan_belt_photo", "label": "Old Fan Belt before replacement Photo"},
    {"key": "new_fan_belt_photo", "label": "New Fan Belt After Replacement Photo"},
    {"key": "coolant_poured_photo", "label": "Radiator Coolant been poured Photo"},
    {"key": "old_oil_filter_photo", "label": "Old Oil Filter on DG Photo"},
    {"key": "new_oil_filter_photo", "label": "New Oil Filter on DG Photo"},
    {"key": "old_fuel_filter_photo", "label": "Old Fuel Filter Photo"},
    {"key": "new_fuel_filter_photo", "label": "New Fuel Filter Photo"},
    {"key": "old_air_filter_photo", "label": "Old Air Filter"},
    {"key": "new_air_filter_photo", "label": "New Air Filter"},
    {"key": "updated_dg_service_card", "label": "Updated DG Service Card Photo"},
    {"key": "updated_fueling_card", "label": "Updated Fueling Card Photo"},
    {"key": "rectifier_settings_1", "label": "Rectifier settings Photos_1"},
    {"key": "rectifier_settings_2", "label": "Rectifier settings Photos_2"},
    {"key": "rectifier_settings_3", "label": "Rectifier settings Photos_3"},
    {"key": "rectifier_settings_4", "label": "Rectifier settings Photos_4"},
    {"key": "fuel_leakage_signs", "label": "Signs of Fuel leakage along the DG"},
    {"key": "ats_installed_photo", "label": "ATS Installed Photo"},
    {"key": "acdb_photo", "label": "ACDB Photo"},
    {"key": "dg_v_ph1_ph2", "label": "DG Supply Voltage - Ph1 to Ph2 (V) Photo"},
    {"key": "dg_v_ph1_ph3", "label": "DG Supply Voltage - Ph1 to Ph3 (V) Photo"},
    {"key": "dg_v_ph2_ph3", "label": "DG Supply Voltage - Ph2 to Ph3 (V) Photo"},
    {"key": "dg_v_ph1_n", "label": "DG Supply Voltage - Ph1 to Neutral (V) Photo"},
    {"key": "dg_v_ph2_n", "label": "DG Supply Voltage - Ph2 to Neutral (V) Photo"},
    {"key": "dg_v_ph3_n", "label": "DG Supply Voltage - Ph3 to Neutral (V) Photo"},
    {"key": "dg_i_ph1", "label": "DG supply current - Ph1 Current (A) Photo"},
    {"key": "dg_i_ph2", "label": "DG supply current - Ph2 Current (A) Photo"},
    {"key": "dg_i_ph3", "label": "DG supply current - Ph3 Current (A) Photo"},
    {"key": "rectifier_closed", "label": "Full View Rectifier Cabinet Photo (CLOSED)"},
    {"key": "rectifier_open", "label": "Full View Rectifier Cabinet Photo (OPEN)"},
    {"key": "rectifier_controller", "label": "Rectifier Controller Photo"},
    {"key": "rectifier_slots", "label": "Number of rectifier module slots Photo"},
    {"key": "rectifier_cabinet_serial", "label": "Rectifier Cabinet Serial Number"},
    {"key": "rectifier_controller_serial", "label": "Rectifier Controller Serial Number"},
    {"key": "cleaning_modules", "label": "Photo when cleaning modules"},
    {"key": "system_voltage_photo", "label": "System Voltage Photo"},
    {"key": "hybrid_system_site", "label": "Hybrid System at Site"},
    {"key": "battery_bank_full_view", "label": "Battery Bank Full View Photo"},
    {"key": "battery_capacity_photo", "label": "Battery Capacity Photo"},
    {"key": "tower_full_photo", "label": "Tower Full Photo"},
    {"key": "tower_legs", "label": "Tower Legs 1,2,3,4"},
    {"key": "rectifier_photo", "label": "Rectifier"},
    {"key": "acdb_dcdb", "label": "ACDB, DCDB"},
    {"key": "dg_photo", "label": "DG"},
    {"key": "tenant_equipment", "label": "Tenant Equipment"},
    {"key": "shelter_interior", "label": "Shelter Interior After Cleaning"},
    {"key": "shelter_lighting", "label": "Shelter Lighting"},
    {"key": "shelter_door_status", "label": "Shelter Door status"},
    {"key": "bbs_door_status", "label": "BBS Door status"},
    {"key": "unused_equipment", "label": "Any unused Equipment on site"},
    {"key": "site_perimeter", "label": "Site Perimeter"},
    {"key": "site_janitorial", "label": "Site Janitorial"},
    {"key": "gate_lock", "label": "Gate Lock"}
]

# Holiday configurations
_HOLIDAYS_CONFIG = {
    2024: [
        {"date": "2024-01-01", "name": "New Year's Day"},
        {"date": "2024-02-16", "name": "Archbishop Janani Luwum Day"},
        {"date": "2024-03-08", "name": "International Women's Day"},
        {"date": "2024-04-05", "name": "Good Friday"},
        {"date": "2024-04-08", "name": "Easter Monday"},
        {"date": "2024-05-01", "name": "Labour Day"},
        {"date": "2024-06-03", "name": "Uganda Martyrs' Day"},
        {"date": "2024-06-09", "name": "National Heroes' Day"},
        {"date": "2024-10-09", "name": "Independence Day"},
        {"date": "2024-12-25", "name": "Christmas Day"},
        {"date": "2024-12-26", "name": "Boxing Day"},
    ],
    2025: [
        {"date": "2025-01-01", "name": "New Year's Day"},
        {"date": "2025-02-16", "name": "Archbishop Janani Luwum Day"},
        {"date": "2025-03-08", "name": "International Women's Day"},
        {"date": "2025-04-18", "name": "Good Friday"},
        {"date": "2025-04-21", "name": "Easter Monday"},
        {"date": "2025-05-01", "name": "Labour Day"},
        {"date": "2025-06-03", "name": "Uganda Martyrs' Day"},
        {"date": "2025-06-09", "name": "National Heroes' Day"},
        {"date": "2025-10-09", "name": "Independence Day"},
        {"date": "2025-12-25", "name": "Christmas Day"},
        {"date": "2025-12-26", "name": "Boxing Day"},
    ],
    2026: [
        {"date": "2026-01-01", "name": "New Year's Day"},
        {"date": "2026-01-26", "name": "NRM Liberation Day"},
        {"date": "2026-02-16", "name": "Archbishop Janani Luwum Day"},
        {"date": "2026-03-08", "name": "International Women's Day"},
        {"date": "2026-04-03", "name": "Good Friday"},
        {"date": "2026-04-06", "name": "Easter Monday"},
        {"date": "2026-05-01", "name": "Labour Day"},
        {"date": "2026-06-03", "name": "Uganda Martyrs' Day"},
        {"date": "2026-06-09", "name": "National Heroes' Day"},
        {"date": "2026-10-09", "name": "Independence Day"},
        {"date": "2026-12-25", "name": "Christmas Day"},
        {"date": "2026-12-26", "name": "Boxing Day"},
    ],
}

# UID role prefixes
_ROLE_UID_PREFIX = {
    "developer": "DEV",
    "technician": "TEC",
    "staff": "STF",
    "manager": "MGR",
    "general_manager": "GMR",
}
ROLE_UID_PREFIX = _ROLE_UID_PREFIX

# Outage signal rules
_OUTAGE_SIGNAL_RULES = [
    {
        "name": "site_down",
        "terms": ("site down", "network down", "outage", "off air", "no service", "link down", "total blackout"),
        "score": 26,
        "critical": True,
        "category": "OUTAGE_RESPONSE",
        "flag": "Network/site outage reported",
        "recommendation": "Escalate immediate outage response with NOC and field teams.",
    },
    {
        "name": "power_loss",
        "terms": ("no power", "power failure", "blackout", "mains down", "grid down", "genset failed", "generator failed", "rectifier fault"),
        "score": 18,
        "critical": True,
        "category": "POWER_CHAIN",
        "flag": "Power outage indicators detected",
        "recommendation": "Prioritize power restoration checks and generator failover validation.",
    },
    {
        "name": "transmission_fault",
        "terms": ("fiber cut", "transmission down", "backhaul down", "microwave down", "los", "transmission alarm"),
        "score": 20,
        "critical": True,
        "category": "TRANSMISSION",
        "flag": "Transmission outage indicators detected",
        "recommendation": "Raise transmission incident handling and confirm backhaul restoration path.",
    },
    {
        "name": "service_degradation",
        "terms": ("degraded", "intermittent", "flapping", "unstable", "packet loss", "high latency", "poor service", "slow service"),
        "score": 10,
        "critical": False,
        "category": "SERVICE_DEGRADATION",
        "flag": "Service degradation indicators detected",
        "recommendation": "Capture service quality evidence and investigate recurring degradation trends.",
    },
    {
        "name": "alarm_pressure",
        "terms": ("critical alarm", "major alarm", "multiple alarms", "alarm flood"),
        "score": 12,
        "critical": False,
        "category": "ALARM_PRESSURE",
        "flag": "High alarm pressure reported",
        "recommendation": "Correlate alarms with root cause and clear non-actionable noise.",
    },
    {
        "name": "access_security",
        "terms": ("forced access", "security issue", "site inaccessible", "access denied", "break in", "vandal", "theft"),
        "score": 16,
        "critical": True,
        "category": "ACCESS_SECURITY",
        "flag": "Access/security incident indicators detected",
        "recommendation": "Coordinate access, safety, and security teams before restoration work proceeds.",
    },
]

# Snag classifications
SNAG_KEYWORDS = {
    "GATE_NOT_CLOSED": ["gate not closed", "gate open", "gate unlocked"],
    "POWER_FAILURE": ["no power", "power failure", "blackout", "mains down", "grid down"],
    "BATTERY_ISSUE": ["battery low", "battery dead", "battery fault", "battery weak"],
    "ACCESS_ISSUE": ["no access", "locked site", "access denied", "site inaccessible"],
    "FIBER_ISSUE": ["fiber cut", "link down", "transmission down", "no link"],
    "SECURITY_BREACH": ["theft", "vandal", "break in", "security issue", "intrusion"],
    "RECTIFIER_ISSUE": ["rectifier fault", "rectifier failed", "rectifier alarm"],
    "GENERATOR_ISSUE": ["generator failed", "genset failed", "dg failed", "dg fault"],
    "FUEL_RISK": ["low fuel", "fuel theft", "fuel leak", "no fuel"],
    "COOLING_ISSUE": ["high temperature", "cooling fault", "fan failed", "overheat"],
    "MISSING_SOLAR_PANEL": ["missing solar panel", "solar panel theft", "solar panel damage", "solar panel issue"],
}

OUTAGE_SNAGS = {"POWER_FAILURE", "BATTERY_ISSUE", "FIBER_ISSUE", "RECTIFIER_ISSUE", "GENERATOR_ISSUE", "COOLING_ISSUE"}
CRITICAL_SNAGS = {"GATE_NOT_CLOSED", "POWER_FAILURE", "BATTERY_ISSUE", "FIBER_ISSUE", "SECURITY_BREACH", "RECTIFIER_ISSUE", "GENERATOR_ISSUE", "FUEL_RISK", "COOLING_ISSUE", "MISSING_SOLAR_PANEL"}

SNAG_CLASSIFICATIONS = {
    "GATE_NOT_CLOSED": {"category": "ACCESS_SECURITY", "label": "Gate security issue", "score": 12},
    "POWER_FAILURE": {"category": "POWER_CHAIN", "label": "Power failure", "score": 24},
    "BATTERY_ISSUE": {"category": "POWER_CHAIN", "label": "Battery issue", "score": 18},
    "ACCESS_ISSUE": {"category": "ACCESS_SECURITY", "label": "Access issue", "score": 12},
    "FIBER_ISSUE": {"category": "TRANSMISSION", "label": "Transmission issue", "score": 22},
    "SECURITY_BREACH": {"category": "ACCESS_SECURITY", "label": "Security breach", "score": 20},
    "RECTIFIER_ISSUE": {"category": "POWER_CHAIN", "label": "Rectifier issue", "score": 18},
    "GENERATOR_ISSUE": {"category": "POWER_CHAIN", "label": "Generator issue", "score": 18},
    "FUEL_RISK": {"category": "POWER_CHAIN", "label": "Fuel risk", "score": 16},
    "COOLING_ISSUE": {"category": "POWER_CHAIN", "label": "Cooling issue", "score": 14},
    "MISSING_SOLAR_PANEL": {"category": "POWER_CHAIN", "label": "Missing solar panel", "score": 16},
}

# Breach reason categories
BREACH_REASON_CATEGORIES = {
    "RESOURCE_DELAY",
    "MISSING_DATA",
    "APPROVAL_BOTTLENECK",
    "SYSTEM_ISSUE",
    "EXTERNAL_DEPENDENCY",
}

# Workflow trace labels
WORKFLOW_TRACE_LABELS = {
    "created": "Stage Created At (UTC)",
    "assigned": "Stage Assigned At (UTC)",
    "started": "Stage Started At (UTC)",
    "resolved": "Stage Resolved At (UTC)",
    "closed": "Stage Closed At (UTC)",
}
