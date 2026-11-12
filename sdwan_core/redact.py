"""Secret redaction applied to everything written to disk (shared with the standalone collector).

Keys that look like secrets, crypt-style hashes ($1$/$6$/$8$/$9$...), XML secret elements and
secret values inside CLI config text are replaced with '[redacted]'.
"""
from __future__ import annotations

import json
import re

# Keys whose values are secrets (session tokens, passwords, keys) – never written to disk.
_SECRET_KEY = re.compile(r"(?i)(token|session|csrf|password|passwd|secret|passphrase|psk|auth-key|private-key|"
                         r"authentication-key|encryption-key|apikey|api-key|api_key|key-hash|community|(^|[-_])key$)")
# Encrypted secrets in device config ("$8$...", "$9$...", type-6/7 strings).
_SECRET_VAL = re.compile(r"^\$\d\$")


# Inside config text: keep the keyword, hide the value that follows it.
_CFG_SECRET = re.compile(
    r"(?im)\b(password|secret|key-string|pre-shared-key|community|auth-key|authentication-key|"
    r"priv\s+aes\s+\d+|auth\s+sha|shared-secret|key)(\s+(?:[0-9]\s+)?)(\S+)")


_SECRET_TAGS = r"password|secret|key|key-string|pre-shared-key|community|community-name|auth-key|" \
               r"authentication-key|shared-secret|priv-password|auth-password|psk|md5"
# XML (raw or HTML-escaped): <secret>VALUE</secret>
_XML_SECRET = re.compile(rf"(?i)(<|&lt;)({_SECRET_TAGS})(>|&gt;)([^<&]+)(<|&lt;)/\2(>|&gt;)")
# Any crypt-style hash/encrypted value anywhere: $1$.., $6$.., $8$.., $9$..
_HASH = re.compile(r"\$\d+\$[^\s<>\"'&]+")


def redact_config(text: str) -> str:
    text = _XML_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[redacted]{m.group(5)}/{m.group(2)}{m.group(6)}", text)
    text = _HASH.sub("[redacted]", text)
    return _CFG_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)


def secret_path(path: str) -> bool:
    """True if any segment of a setting path (e.g. /snmp/community[0]/name) names a secret."""
    return any(_SECRET_KEY.search(seg.split("[")[0]) for seg in path.split("/") if seg)


def _blank_vip(o):
    """Inside a secret-named template field, hide every stored value (vipValue); variable names stay."""
    if isinstance(o, dict):
        return {k: ("[redacted]" if k == "vipValue" and isinstance(v, (str, int, float)) and v != "" else _blank_vip(v))
                for k, v in o.items()}
    if isinstance(o, list):
        return [_blank_vip(x) for x in o]
    return o


def _template_definition(v: str) -> str:
    """Feature template definitions arrive as JSON text: parse, redact, re-encode (unparsable -> as config text)."""
    try:
        return json.dumps(redact(json.loads(v)))
    except ValueError:
        return redact_config(v)


def redact(obj):
    """Recursively replace secret values with '[redacted]'."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _SECRET_KEY.search(k) and isinstance(v, (str, int)) and v != "":
                out[k] = "[redacted]"
            elif _SECRET_KEY.search(k) and isinstance(v, (dict, list)):
                out[k] = redact(_blank_vip(v))  # feature-template style {"vipValue": ...}
            elif k == "templateDefinition" and isinstance(v, str):
                out[k] = _template_definition(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str) and _SECRET_VAL.match(obj):
        return "[redacted]"
    if isinstance(obj, str) and ("\n" in obj or "<" in obj or "$" in obj):
        return redact_config(obj)
    return obj
