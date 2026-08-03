import frappe
from erp_ai.ai.decorators import ai_tool
from erp_ai.ai.tools._security import validate_doctype, validate_fieldname, check_permission

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


@ai_tool(
    name="create_dashboard",
    description=(
        "Create a Dashboard and attach one or more existing Dashboard Charts to it. "
        "Use create_dashboard_chart first for any chart that doesn't exist yet."
    ),
    parameters={
        "dashboard_name": {"type": "string", "required": True},
        "chart_names": {"type": "array", "description": "Names of existing Dashboard Charts to attach."},
        "module": {"type": "string"},
    },
)
def create_dashboard(dashboard_name, chart_names=None, module=None, **kwargs):
    if not frappe.has_permission("Dashboard", "create"):
        frappe.throw("You do not have permission to create dashboards.")

    if frappe.db.exists("Dashboard", dashboard_name):
        frappe.throw(f"A dashboard named '{dashboard_name}' already exists.")

    charts = []
    for chart_name in (chart_names or []):
        if not frappe.db.exists("Dashboard Chart", chart_name):
            frappe.throw(f"Dashboard Chart '{chart_name}' does not exist. Create it first with create_dashboard_chart.")
        if not frappe.has_permission("Dashboard Chart", "read", doc=chart_name):
            frappe.throw(f"You do not have permission to read chart '{chart_name}'.")
        charts.append({"chart": chart_name})

    doc = frappe.get_doc({
        "doctype": "Dashboard",
        "dashboard_name": dashboard_name,
        "module": module or "Core",
        "is_default": 0,
        "charts": charts,
    })
    doc.insert()
    return {"status": "success", "dashboard_name": doc.name}
