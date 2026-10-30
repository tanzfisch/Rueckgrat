from .sweeper import MaintenanceSweeper, MaintenanceTask
from .conversation_summary import ConversationSummaryTask

def maintenance_tasks(db, infrastructure) -> list[MaintenanceTask]:
    """the hub's maintenance tasks in run order, for the nightly sweeper and hub management. a new task goes here"""
    return [
        ConversationSummaryTask(db, infrastructure),
    ]

__all__ = ["MaintenanceSweeper", "MaintenanceTask", "ConversationSummaryTask", "maintenance_tasks"]
