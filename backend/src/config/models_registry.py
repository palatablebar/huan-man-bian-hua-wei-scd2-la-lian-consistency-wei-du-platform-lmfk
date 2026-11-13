"""Import every model module so Base.metadata is complete before create_all()."""
from src.models import (  # noqa: F401
    audit_log,
    build_run,
    conflict_item,
    customer_snapshot,
    dim_customer,
    merge_rule,
    retraction_backup,
    retraction_batch,
    source_system,
    user,
)
