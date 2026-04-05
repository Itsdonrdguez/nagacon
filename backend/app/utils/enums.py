from enum import Enum


class OpportunityStatus(str, Enum):
    NEW = "new"
    UNDER_REVIEW = "under_review"
    BID = "bid"
    NO_BID = "no_bid"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    AWARDED = "awarded"
    LOST = "lost"


class PipelineStatus(str, Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    BID = "BID"
    NO_BID = "NO_BID"
    SUBMITTED = "SUBMITTED"
