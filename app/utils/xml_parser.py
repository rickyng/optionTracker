import logging
from typing import Any

from defusedxml import ElementTree as SafeET

logger = logging.getLogger(__name__)


def parse_flex_send_response(xml_text: str) -> dict[str, str]:
    """Parse SendRequest XML response."""
    logger.debug("SendRequest raw response: %s", xml_text[:500])
    root = SafeET.fromstring(xml_text)
    status = root.findtext("Status", "Fail")
    ref_code = root.findtext("ReferenceCode", "")
    url = root.findtext("Url", "")
    error_code = root.findtext("ErrorCode", "")
    error_msg = root.findtext("ErrorMessage", "")
    if status != "Success":
        logger.warning(
            "SendRequest failed: status=%s, ErrorCode=%s, ErrorMessage=%s",
            status,
            error_code,
            error_msg,
        )
    return {
        "status": status,
        "reference_code": ref_code,
        "url": url,
        "error_code": error_code,
        "error_message": error_msg,
    }


def parse_flex_statement_response(content: str) -> dict[str, Any]:
    """Parse GetStatement response. Handles XML and raw CSV."""
    content = content.strip()

    # Raw CSV response
    if content.startswith('"') or "ClientAccountID" in content:
        return {"status": "Success", "data": content, "format": "csv"}

    try:
        root = SafeET.fromstring(content)
        tag = root.tag.lower()

        if "flexstatementresponse" in tag:
            status = root.findtext("Status", "Fail")
            return {"status": status, "data": None, "format": "xml"}

        if "flexqueryresponse" in tag:
            return {"status": "Success", "data": content, "format": "xml"}

    except Exception:
        pass

    return {"status": "Unknown", "data": content, "format": "unknown"}
