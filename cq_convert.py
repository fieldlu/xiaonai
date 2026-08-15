"""CQ code to OneBot v11 array format conversion."""
import re

_CQ_RE = re.compile(r'\[CQ:(\w+)((?:,(?:[a-zA-Z0-9_.\-]+(?:=[^,\]]*)?)?)*)\]')

def cq_to_array(text):
    if not text or "CQ:" not in text:
        return text
    result = []
    last_end = 0
    for m in _CQ_RE.finditer(text):
        if m.start() > last_end:
            prefix = text[last_end:m.start()]
            if prefix:
                result.append({"type": "text", "data": {"text": prefix}})
        cq_type = m.group(1)
        params_str = m.group(2)
        params = {}
        if params_str:
            for part in params_str.split(",")[1:]:
                if "=" in part:
                    k, v = part.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k == "qq" and v.lstrip("-").isdigit():
                        params[k] = int(v)
                    elif v.isdigit():
                        params[k] = int(v)
                    else:
                        params[k] = v
                elif part:
                    params[part.strip()] = ""
        result.append({"type": cq_type, "data": params})
        last_end = m.end()
    if last_end < len(text):
        suffix = text[last_end:]
        if suffix:
            result.append({"type": "text", "data": {"text": suffix}})
    return result if result else text


def cq_array_convert(segments):
    """Process a message array, converting CQ codes embedded in text segments.
    
    Args:
        segments: list of OneBot message segments
    Returns:
        Modified list with CQ codes in text segments converted to proper at/image/etc segments
    """
    if not isinstance(segments, list):
        return segments
    
    result = []
    for seg in segments:
        if seg.get("type") == "text":
            text = seg.get("data", {}).get("text", "")
            if "CQ:" in text:
                # Convert CQ codes in this text segment
                converted = cq_to_array(text)
                if isinstance(converted, list):
                    result.extend(converted)
                else:
                    result.append(seg)
            else:
                result.append(seg)
        else:
            result.append(seg)
    return result
