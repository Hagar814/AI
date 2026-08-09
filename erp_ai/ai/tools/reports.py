import frappe
from erp_ai.ai.decorators import ai_tool
from erp_ai.ai.tools._security import (
    validate_doctype,
    validate_fieldname,
    validate_filters,
    check_permission,
)

# DEBUG: proves this exact file is the one Python actually imported (not a
# cached .pyc or an old copy elsewhere on the path). Runs once per worker
# process, at import time, before any tool below is defined/registered.
# Writes to the Error Log doctype (Desk > Error Log) so it's visible without
# needing terminal/log-file access. Remove once confirmed working.
def _debug_log(title, message):
    try:
        frappe.log_error(title=title[:140], message=message)
    except Exception:
        pass


print("[ERP_AI_DEBUG] reports.py module loaded from:", __file__)
_debug_log("ERP_AI_DEBUG reports.py loaded", f"Module loaded from: {__file__}")

# Real Dashboard Chart schema (verified against frappe/frappe's
# dashboard_chart.py controller - the original repo's system prompt had the
# 'type' and 'chart_type' meanings backwards, which meant AI-created charts
# would fail validation or misrender):
#
#   document_type            -> the DocType the chart reads from
#   type                     -> VISUAL style: Line | Bar | Percentage | Pie | Donut
#   chart_type               -> AGGREGATION mode: Count | Sum | Average | Group By
#   based_on                 -> date field, time-series mode only
#   value_based_on            -> value field, time-series Sum/Average only
#   timeseries / time_interval -> time-series mode only
#   group_by_based_on         -> field to group by, group_by mode only
#   group_by_type              -> Count | Sum | Average, group_by mode only
#   aggregate_function_based_on -> value field, group_by Sum/Average only

ALLOWED_VISUAL_TYPES = {"Line", "Bar", "Percentage", "Pie", "Donut"}
ALLOWED_AGGREGATES = {"Count", "Sum", "Average"}
ALLOWED_TIME_INTERVALS = {"Daily", "Weekly", "Monthly", "Quarterly", "Yearly"}

# Number Card schema (the KPI "card" widgets, e.g. "Total Sales Today"),
# based on frappe/frappe's number_card doctype:
#
#   type                      -> "Document Type" (the only mode we expose here;
#                                 Report/Custom cards run a saved report or a
#                                 whitelisted Python method instead of a DocType
#                                 query, which is out of scope for an AI tool)
#   document_type             -> the DocType the card counts/aggregates
#   function                  -> Count | Sum | Average | Minimum | Maximum
#   aggregate_function_based_on -> value field, required for Sum/Average/Minimum/Maximum
#   filters_json               -> same list-of-conditions format as list view filters
#   show_percentage_stats      -> if 1, shows +/- change vs the previous stats_time_interval
#   stats_time_interval         -> Daily | Weekly | Monthly | Yearly, only used with the above
#
# IMPORTANT: verify this against the actual installed Frappe version once a
# bench is available (`bench --site <site> console` ->
# frappe.get_meta("Number Card").fields) - the fieldnames above are based on
# the stable, long-standing "Doctype Dashboard View" Number Card feature but
# have not been runtime-verified in this sandbox (no Frappe install here).
ALLOWED_CARD_FUNCTIONS = {"Count", "Sum", "Average", "Minimum", "Maximum"}


@ai_tool(
    name="create_report",
    description=(
        "Create and save a Report Builder report (a saved, filterable list view) on an "
        "existing DocType. Raw-SQL Query Reports and Script Reports are not offered here "
        "since they execute arbitrary code every time anyone opens them - ask a System "
        "Manager to create those directly in the desk UI if one is truly needed."
    ),
    parameters={
        "report_title": {"type": "string", "required": True},
        "ref_doctype": {"type": "string", "required": True, "description": "DocType the report is based on."},
        "module": {"type": "string"},
    },
)
def create_report(report_title, ref_doctype, module=None, **kwargs):
    if not frappe.has_permission("Report", "create"):
        frappe.throw("You do not have permission to create reports.")

    validate_doctype(ref_doctype)
    check_permission(ref_doctype, "read")

    if frappe.db.exists("Report", {"report_name": report_title}):
        frappe.throw(f"A report named '{report_title}' already exists.")

    doc = frappe.get_doc({
        "doctype": "Report",
        "report_name": report_title,
        "report_type": "Report Builder",
        "ref_doctype": ref_doctype,
        "is_standard": "No",
        "module": module or frappe.get_meta(ref_doctype).module or "Core",
    })
    doc.insert()
    return {"status": "success", "report_name": doc.name}


@ai_tool(
    name="create_dashboard_chart",
    description=(
        "Create a Dashboard Chart on a DocType, for statistics/analysis. "
        "Two modes: 'time_series' (a trend of count/sum/average over a date field, e.g. "
        "'monthly sales total') or 'group_by' (count/sum/average grouped by a field, "
        "e.g. 'sales by customer')."
    ),
    parameters={
        "chart_name": {"type": "string", "required": True},
        "doctype": {"type": "string", "required": True},
        "mode": {"type": "string", "required": True, "description": "time_series | group_by"},
        "aggregate": {"type": "string", "description": "Count, Sum, or Average. Default Count."},
        "value_field": {"type": "string", "description": "Numeric field to sum/average. Required unless aggregate is Count."},
        "date_field": {"type": "string", "description": "Date field for time_series mode, e.g. posting_date."},
        "group_by_field": {"type": "string", "description": "Field to group by, for group_by mode."},
        "time_interval": {"type": "string", "description": "Daily, Weekly, Monthly, Quarterly, Yearly. Default Monthly."},
        "visual_type": {"type": "string", "description": "Line, Bar, Percentage, Pie, Donut. Default Bar."},
        "module": {"type": "string"},
    },
)
def create_dashboard_chart(chart_name, doctype, mode, aggregate="Count", value_field=None,
                            date_field=None, group_by_field=None, time_interval="Monthly",
                            visual_type="Bar", module=None, **kwargs):
    validate_doctype(doctype)
    check_permission(doctype, "read")
    if not frappe.has_permission("Dashboard Chart", "create"):
        frappe.throw("You do not have permission to create dashboard charts.")

    if frappe.db.exists("Dashboard Chart", chart_name):
        frappe.throw(f"A chart named '{chart_name}' already exists.")

    mode = (mode or "").lower().strip()
    aggregate = aggregate if aggregate in ALLOWED_AGGREGATES else "Count"
    visual_type = visual_type if visual_type in ALLOWED_VISUAL_TYPES else "Bar"
    time_interval = time_interval if time_interval in ALLOWED_TIME_INTERVALS else "Monthly"

    chart_doc = {
        "doctype": "Dashboard Chart",
        "chart_name": chart_name,
        "document_type": doctype,
        "type": visual_type,
        "module": module or frappe.get_meta(doctype).module or "Core",
        # Dashboard Chart has `filters_json` as a mandatory field even when
        # there are no filters - Frappe rejects the insert with "Value
        # missing for Dashboard Chart: Filters JSON" if it's left unset.
        "filters_json": "[]",
    }

    if mode == "time_series":
        if not date_field:
            frappe.throw("`date_field` is required for time_series charts.")
        validate_fieldname(doctype, date_field)

        if aggregate != "Count":
            if not value_field:
                frappe.throw("`value_field` is required for Sum/Average time_series charts.")
            validate_fieldname(doctype, value_field)

        chart_doc.update({
            "chart_type": aggregate,
            "based_on": date_field,
            "value_based_on": value_field,
            "timeseries": 1,
            "time_interval": time_interval,
            # Required alongside timeseries=1 - without it the chart has no
            # window to compute over. "Last Year" gives the widest default
            # view; the model can still ask the user for a narrower one.
            "timespan": "Last Year",
        })

    elif mode == "group_by":
        if not group_by_field:
            frappe.throw("`group_by_field` is required for group_by charts.")
        validate_fieldname(doctype, group_by_field)

        if aggregate != "Count":
            if not value_field:
                frappe.throw("`value_field` is required for Sum/Average group_by charts.")
            validate_fieldname(doctype, value_field)

        chart_doc.update({
            "chart_type": "Group By",
            "group_by_based_on": group_by_field,
            "group_by_type": aggregate,
            "aggregate_function_based_on": value_field,
        })

    else:
        frappe.throw("`mode` must be either 'time_series' or 'group_by'.")

    doc = frappe.get_doc({k: v for k, v in chart_doc.items() if v is not None})
    doc.insert()
    return {"status": "success", "chart_name": doc.name}


def _filters_dict_to_json(doctype, filters):
    """Number Card / Dashboard Chart `filters_json` uses the list-view filter
    format (a list of [fieldname, operator, value] conditions), not the plain
    {field: value} dict our other tools use. We still validate keys through
    validate_filters (real fields only, permission-safe), then convert."""
    clean = validate_filters(doctype, filters)
    return frappe.as_json([[field, "=", value] for field, value in clean.items()])


@ai_tool(
    name="create_number_card",
    description=(
        "Create a Number Card - a single-number KPI widget for a Dashboard, e.g. "
        "'Total Sales Today', 'Open Purchase Orders', 'Average Order Value'. "
        "Counts/aggregates over a single DocType, optionally filtered. For a trend or "
        "breakdown instead of one number, use create_dashboard_chart."
    ),
    parameters={
        "card_name": {"type": "string", "required": True, "description": "Label shown on the card."},
        "doctype": {"type": "string", "required": True},
        "function": {"type": "string", "description": "Count | Sum | Average | Minimum | Maximum. Default Count."},
        "value_field": {"type": "string", "description": "Numeric field to aggregate. Required unless function is Count."},
        "filters": {"type": "object", "description": "Optional {field: value} filters, e.g. {'status': 'Open'}."},
        "show_percentage_stats": {"type": "boolean", "description": "Show +/- change vs the previous period. Default false."},
        "stats_time_interval": {"type": "string", "description": "Daily | Weekly | Monthly | Yearly. Only used with show_percentage_stats."},
        "module": {"type": "string"},
    },
)
def create_number_card(card_name, doctype, function="Count", value_field=None, filters=None,
                        show_percentage_stats=False, stats_time_interval="Monthly",
                        module=None, **kwargs):
    # DEBUG: confirms the AI actually called this tool, and with what args.
    # Remove once confirmed working.
    print(f"[ERP_AI_DEBUG] create_number_card called: card_name={card_name!r} "
          f"doctype={doctype!r} function={function!r} value_field={value_field!r} filters={filters!r}")
    _debug_log(
        "ERP_AI_DEBUG create_number_card called",
        f"card_name={card_name!r}\ndoctype={doctype!r}\nfunction={function!r}\n"
        f"value_field={value_field!r}\nfilters={filters!r}",
    )

    validate_doctype(doctype)
    check_permission(doctype, "read")
    if not frappe.has_permission("Number Card", "create"):
        frappe.throw("You do not have permission to create number cards.")

    if frappe.db.exists("Number Card", card_name):
        frappe.throw(f"A number card named '{card_name}' already exists.")

    function = function if function in ALLOWED_CARD_FUNCTIONS else "Count"
    if function != "Count":
        if not value_field:
            frappe.throw(f"`value_field` is required for the '{function}' function.")
        validate_fieldname(doctype, value_field)

    stats_time_interval = stats_time_interval if stats_time_interval in ALLOWED_TIME_INTERVALS else "Monthly"

    card_doc = {
        "doctype": "Number Card",
        "label": card_name,
        "type": "Document Type",
        "document_type": doctype,
        "function": function,
        "aggregate_function_based_on": value_field,
        "filters_json": _filters_dict_to_json(doctype, filters),
        "module": module or frappe.get_meta(doctype).module or "Core",
        "show_percentage_stats": 1 if show_percentage_stats else 0,
    }
    if show_percentage_stats:
        card_doc["stats_time_interval"] = stats_time_interval

    doc = frappe.get_doc({k: v for k, v in card_doc.items() if v is not None})
    doc.insert()

    print(f"[ERP_AI_DEBUG] create_number_card SAVED as: {doc.name}")
    _debug_log("ERP_AI_DEBUG create_number_card saved", f"card_name={doc.name!r}")

    return {"status": "success", "card_name": doc.name}


@ai_tool(
    name="create_dashboard",
    description=(
        "Create a Dashboard and attach one or more existing Dashboard Charts and/or "
        "Number Cards to it. Use create_dashboard_chart / create_number_card first for "
        "any chart or card that doesn't exist yet. At least one of chart_names or "
        "card_names must be given."
    ),
    parameters={
        "dashboard_name": {"type": "string", "required": True},
        "chart_names": {"type": "array", "description": "Names of existing Dashboard Charts to attach."},
        "card_names": {"type": "array", "description": "Names of existing Number Cards to attach."},
        "module": {"type": "string"},
    },
)
def create_dashboard(dashboard_name, chart_names=None, card_names=None, module=None, **kwargs):
    # DEBUG: remove once confirmed working.
    print(f"[ERP_AI_DEBUG] create_dashboard called: dashboard_name={dashboard_name!r} "
          f"chart_names={chart_names!r} card_names={card_names!r}")
    _debug_log(
        "ERP_AI_DEBUG create_dashboard called",
        f"dashboard_name={dashboard_name!r}\nchart_names={chart_names!r}\ncard_names={card_names!r}",
    )

    if not frappe.has_permission("Dashboard", "create"):
        frappe.throw("You do not have permission to create dashboards.")

    if frappe.db.exists("Dashboard", dashboard_name):
        frappe.throw(f"A dashboard named '{dashboard_name}' already exists.")

    if not (chart_names or card_names):
        frappe.throw("Provide at least one of `chart_names` or `card_names`.")

    charts = []
    for chart_name in (chart_names or []):
        if not frappe.db.exists("Dashboard Chart", chart_name):
            frappe.throw(f"Dashboard Chart '{chart_name}' does not exist. Create it first with create_dashboard_chart.")
        if not frappe.has_permission("Dashboard Chart", "read", doc=chart_name):
            frappe.throw(f"You do not have permission to read chart '{chart_name}'.")
        charts.append({"chart": chart_name})

    cards = []
    for card_name in (card_names or []):
        if not frappe.db.exists("Number Card", card_name):
            frappe.throw(f"Number Card '{card_name}' does not exist. Create it first with create_number_card.")
        if not frappe.has_permission("Number Card", "read", doc=card_name):
            frappe.throw(f"You do not have permission to read card '{card_name}'.")
        cards.append({"card": card_name})

    doc = frappe.get_doc({
        "doctype": "Dashboard",
        "dashboard_name": dashboard_name,
        "module": module or "Core",
        "is_default": 0,
        "charts": charts,
        "cards": cards,
    })
    doc.insert()

    print(f"[ERP_AI_DEBUG] create_dashboard SAVED as: {doc.name} "
          f"(charts={len(charts)}, cards={len(cards)})")
    _debug_log(
        "ERP_AI_DEBUG create_dashboard saved",
        f"dashboard_name={doc.name!r}\ncharts={len(charts)}\ncards={len(cards)}",
    )

    return {"status": "success", "dashboard_name": doc.name}