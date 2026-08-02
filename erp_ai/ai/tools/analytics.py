import frappe
from erp_ai.ai.decorators import ai_tool
from erp_ai.ai.tools._security import (
    validate_doctype,
    validate_fieldname,
    validate_fields,
    validate_filters,
    validate_order_by,
    check_permission,
    AGGREGATE_FUNCTIONS,
)

# Frappe's ORM (get_list/get_all/get_value) now rejects SQL function calls
# written as plain strings in `fields` - e.g. "count(name) as value" raises
# "SQL functions are not allowed as strings in SELECT" on current Frappe
# versions (this landed alongside the CVE-2025-30212/30217 SQL-injection
# fixes). Aggregates must be passed as a dict instead:
#   {"COUNT": "name", "as": "value"}   ->  COUNT(`name`) AS `value`
# See: https://github.com/frappe/frappe/pull/32381
SQL_FUNCTION = {"count": "COUNT", "sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}


def _agg_field(fn, field, alias):
    """Build a Frappe-ORM-safe aggregate field dict, e.g. {'SUM': 'grand_total', 'as': 'value'}."""
    return {SQL_FUNCTION[fn]: field or "*", "as": alias}


def _default_order_field(doctype):
    try:
        meta = frappe.get_meta(doctype)
        fieldnames = {d.fieldname for d in meta.fields}
        for f in ("posting_date", "transaction_date", "date"):
            if f in fieldnames:
                return f
    except Exception:
        pass
    return "creation"


@ai_tool(
    name="analyze_data",
    description=(
        "Run aggregate analysis on ERPNext data: count, sum, avg, min, max, "
        "group-by totals, or distinct values, plus first/last/list lookups. "
        "Every field name is checked against the DocType's real schema and every "
        "result is filtered by the current user's ERPNext permissions, exactly "
        "like the desk UI - there is no raw-SQL escape hatch."
    ),
    parameters={
        "doctype": {"type": "string", "required": True},
        "operation": {
            "type": "string",
            "required": True,
            "description": "count | sum | avg | min | max | group | distinct | first | last | list",
        },
        "field": {"type": "string", "description": "Field to aggregate/select (required for sum/avg/min/max/distinct)."},
        "fields": {"type": "array", "description": "Fields to return for 'list' / 'first' / 'last'."},
        "filters": {"type": "object"},
        "group_by": {"type": "string", "description": "Field to group by (required for 'group')."},
        "aggregate": {"type": "string", "description": "For 'group': sum | count | avg | min | max. Default sum."},
        "order_by": {"type": "string"},
        "limit": {"type": "integer", "description": "Capped at 500 (100 for 'group'/'distinct')."},
    },
)
def analyze_data(doctype, operation, field=None, fields=None, filters=None,
                  group_by=None, aggregate="sum", order_by=None, limit=20, **kwargs):
    validate_doctype(doctype)
    check_permission(doctype, "read")

    operation = (operation or "").lower().strip()
    limit = max(1, min(int(limit or 20), 500))
    clean_filters = validate_filters(doctype, filters)

    if operation == "count":
        result = frappe.get_list(doctype, filters=clean_filters, fields=[_agg_field("count", "name", "value")])
        return {"operation": "count", "value": (result[0].value if result else 0)}

    if operation in ("sum", "avg", "min", "max"):
        if not field:
            frappe.throw(f"`field` is required for '{operation}'.")
        validate_fieldname(doctype, field)
        result = frappe.get_list(doctype, filters=clean_filters, fields=[_agg_field(operation, field, "value")])
        value = result[0].value if result else 0
        return {"operation": operation, "field": field, "value": value or 0}

    if operation == "distinct":
        if not field:
            frappe.throw("`field` is required for 'distinct'.")
        validate_fieldname(doctype, field)
        result = frappe.get_list(
            doctype, filters=clean_filters,
            fields=[field],
            distinct=1,
            limit_page_length=min(limit, 100),
        )
        return {"operation": "distinct", "field": field, "values": [r[field] for r in result]}

    if operation == "group":
        if not group_by:
            frappe.throw("`group_by` is required for 'group'.")
        validate_fieldname(doctype, group_by)

        agg = (aggregate or "sum").lower()
        if agg not in AGGREGATE_FUNCTIONS:
            frappe.throw(f"Unsupported aggregate: '{agg}'. Use one of {sorted(AGGREGATE_FUNCTIONS)}.")

        value_field = None
        if agg == "count":
            agg_field = _agg_field("count", "name", "value")
        else:
            value_field = field or "name"
            validate_fieldname(doctype, value_field)
            agg_field = _agg_field(agg, value_field, "value")

        result = frappe.get_list(
            doctype,
            filters=clean_filters,
            fields=[f"{group_by} as group_field", agg_field],
            group_by=group_by,
            order_by="value desc",
            limit_page_length=min(limit, 100),
        )
        return {"operation": "group", "group_by": group_by, "aggregate": agg, "field": value_field, "data": result}

    if operation in ("first", "last", "list"):
        select_fields = validate_fields(doctype, fields)

        if operation == "list":
            clean_order = validate_order_by(doctype, order_by)
            page_limit = limit
        else:
            of = order_by or _default_order_field(doctype)
            direction = "asc" if operation == "first" else "desc"
            clean_order = validate_order_by(doctype, f"{of} {direction}")
            page_limit = 1

        return frappe.get_list(
            doctype, filters=clean_filters, fields=select_fields,
            order_by=clean_order, limit_page_length=page_limit,
        )

    frappe.throw(
        f"Unsupported operation: '{operation}'. Use one of: "
        "count, sum, avg, min, max, group, distinct, first, last, list."
    )
