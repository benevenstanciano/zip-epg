from datetime import datetime, timezone
from dateutil import parser


def parse_xmltv_time(value):
    dt = parser.parse(value)
    return dt.astimezone(timezone.utc)


def xmltv_time(dt):
    return dt.strftime("%Y%m%d%H%M%S +0000")


def now_utc():
    return datetime.now(timezone.utc)
