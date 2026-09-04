"""
Key data translation for the kitty keyboard protocol.

The process running inside a pane can request the kitty keyboard
protocol (pushing flags with "CSI > flags u", tracked by BetterScreen).
The terminal that feeds us key data (the multiplexer client of pymux,
or any other prompt_toolkit application) can send keys in the legacy
encoding, in the kitty CSI u encoding, or a mix of both. This module
translates raw key data into the encoding that the pane expects:

- flags == 0: legacy encoding. Kitty CSI u sequences are translated to
  their legacy equivalents; everything else passes through verbatim.
- flags & 0b1 (disambiguate): escape and ctrl/alt combinations are
  encoded as CSI u. Text keys and plain Enter/Tab/Backspace stay
  legacy, as the spec requires.
- flags & 0b1000 (report all keys as escape codes): everything is
  encoded as CSI u.

Key release events are dropped: prompt_toolkit delivers only key
presses. Alternate key codes and text-as-code-points are not
synthesized.
"""
from typing import List, NamedTuple, Tuple, Union

__all__ = ["translate_key_data"]


# Modifier bits. (The encoded value in a CSI u sequence is one plus the
# sum of the set bits.)
_SHIFT = 1
_ALT = 2
_CTRL = 4

# Keyboard protocol flags. (BetterScreen.kitty_keyboard_flags.)
_DISAMBIGUATE = 0b1
_REPORT_ALL_KEYS = 0b1000

# Final bytes of the "CSI 1 ; modifier <letter>" functional key form.
_LETTER_FINALS = "ABCDEFHPQS"


class KeyEvent(NamedTuple):
    "One decoded key event, in the terms of the keyboard protocol."
    code: int  # unicode key code, or the number of the CSI form
    mods: int  # shift/alt/ctrl bitmask (without the +1 offset)
    final: str  # "u", "~" or one of _LETTER_FINALS
    text: str = ""  # reported text, if the terminal sent it


# Parse result items: KeyEvent, or a str to pass through verbatim
# (opaque sequences like device attribute replies).
_Item = Union[KeyEvent, str]


def _split_subparams(part: str) -> List[int]:
    "Split '97:65' into [97, 65]. Empty parts yield []."
    return [int(x) for x in part.split(":") if x]


def _control_or_text_event(char: str) -> KeyEvent:
    """
    Decode a non-escape character into a key event.

    The key code of the protocol is the key without shift, so an upper
    case letter becomes the lower case one plus the shift modifier.
    The spec says it in these words: "the codepoint used is always the
    lower-case (or more technically, un-shifted) version of the key".

    Only letters take that treatment. Which key gives an exclamation
    mark depends on the layout of the user, and the legacy encoding
    does not carry the layout, so a guess there would be a wrong
    answer on most keyboards. Such a character keeps its own code.
    """
    code = ord(char)
    if char == "\r":
        return KeyEvent(13, 0, "u")
    if char == "\t":
        return KeyEvent(9, 0, "u")
    if char == "\x7f":
        return KeyEvent(127, 0, "u")
    if 1 <= code <= 26:  # ctrl+a .. ctrl+z (and \n = ctrl+j)
        return KeyEvent(code + 96, _CTRL, "u")
    if code == 0:  # ctrl+@
        return KeyEvent(64, _CTRL, "u")
    if 28 <= code <= 31:  # ctrl+\ ^ _
        return KeyEvent(code + 64, _CTRL, "u")
    lower = char.lower()
    if char.isupper() and lower != char and len(lower) == 1:
        return KeyEvent(ord(lower), _SHIFT, "u")
    return KeyEvent(code, 0, "u")


def _parse_csi(data: str, start: int) -> Tuple[_Item, int]:
    "Parse a CSI sequence at data[start] ('ESC [')."
    i = start + 2
    params = ""
    while i < len(data):
        char = data[i]
        if "\x40" <= char <= "\x7e":
            break
        params += char
        i += 1
    else:
        # Incomplete sequence. Pass the remainder through untouched.
        return data[start:], len(data) - start

    final = data[i]
    raw = data[start : i + 1]

    # Private markers ("<=>?"): protocol control or a reply, not a key
    # event. Pass through verbatim.
    if params[:1] in ("<", "=", ">", "?"):
        return raw, i + 1 - start

    rows = [_split_subparams(part) for part in params.split(";")] if params else []
    mods = (rows[1][0] - 1) if len(rows) > 1 and rows[1] else 0

    if final == "u":
        # Kitty key event: "CSI key[:alt] ; mods[:event] [; text] u".
        # Release events are dropped.
        if len(rows) > 1 and len(rows[1]) > 1 and rows[1][1] == 3:
            return "", i + 1 - start
        code = rows[0][0] if rows and rows[0] else 0
        text = "".join(chr(n) for n in rows[2]) if len(rows) > 2 else ""
        return KeyEvent(code, max(0, mods), "u", text), i + 1 - start

    if final == "~":
        code = rows[0][0] if rows and rows[0] else 0
        return KeyEvent(code, max(0, mods), "~"), i + 1 - start

    if final in _LETTER_FINALS:
        code = rows[0][0] if rows and rows[0] else 1
        return KeyEvent(code, max(0, mods), final), i + 1 - start

    # Any other CSI sequence: not a key event.
    return raw, i + 1 - start


def _parse_ss3(data: str, start: int) -> Tuple[_Item, int]:
    "Parse an SS3 sequence at data[start] ('ESC O')."
    if start + 2 >= len(data):
        return data[start:], len(data) - start
    char = data[start + 2]
    if char in _LETTER_FINALS:
        return KeyEvent(1, 0, char), 3
    return data[start : start + 3], 3


def _parse_key_data(data: str) -> List[_Item]:
    "Decode raw key data into key events and verbatim pass-throughs."
    items: List[_Item] = []
    i = 0
    length = len(data)
    while i < length:
        char = data[i]
        if char != "\x1b":
            items.append(_control_or_text_event(char))
            i += 1
        elif i + 1 >= length:
            # Trailing escape: the Escape key.
            items.append(KeyEvent(27, 0, "u"))
            break
        else:
            nxt = data[i + 1]
            if nxt == "[":
                item, consumed = _parse_csi(data, i)
            elif nxt == "O":
                item, consumed = _parse_ss3(data, i)
            else:
                # alt+char in the legacy encoding.
                inner = _control_or_text_event(nxt)
                items.append(KeyEvent(inner.code, inner.mods | _ALT, "u"))
                i += 2
                continue
            items.append(item)
            i += consumed
    return items


def _encode_event(event: KeyEvent, flags: int, application_mode: bool) -> str:
    "Encode a key event for a pane with the given protocol flags."
    code, mods, final, text = event
    mods_value = mods + 1

    if final == "u":
        ambiguous = bool(mods & (_CTRL | _ALT)) or code == 27
        if flags & _REPORT_ALL_KEYS or (flags & _DISAMBIGUATE and ambiguous):
            # CSI u form. (The modifier parameter is omitted when no
            # modifiers are held.)
            if mods_value == 1:
                return "\x1b[%du" % code
            return "\x1b[%d;%du" % (code, mods_value)

        # Legacy form.
        if text and not mods & (_CTRL | _ALT):
            # The reported text accounts for shift and the layout.
            return text
        if mods & (_CTRL | _ALT):
            result = "\x1b" if mods & _ALT else ""
            if mods & _CTRL:
                if code == 13:
                    result += "\n"
                elif code == 9:
                    result += "\t"
                elif code == 127:
                    result += "\x08"
                elif 97 <= code <= 122:
                    result += chr(code - 96)
                elif code == 64:
                    result += "\x00"
                elif 92 <= code <= 95:
                    result += chr(code - 64)
                elif code == 27:
                    result += "\x1b"
                else:
                    result += chr(code)
            else:
                char = chr(code)
                if mods & _SHIFT and char.isalpha():
                    char = char.upper()
                result += char
            return result
        char = chr(code)
        if mods & _SHIFT and char.isalpha():
            char = char.upper()
        return {13: "\r", 9: "\t", 27: "\x1b", 127: "\x7f"}.get(char, char)

    if final == "~":
        if mods == 0:
            return "\x1b[%d~" % code
        return "\x1b[%d;%d~" % (code, mods_value)

    # Functional keys with a letter final byte.
    if mods == 0 and not flags & _REPORT_ALL_KEYS:
        if application_mode and final in "ABCD":
            return "\x1bO" + final
        if final in "PQRS":
            return "\x1bO" + final
        return "\x1b[" + final
    if mods == 0:
        return "\x1b[1%s" % final
    return "\x1b[1;%d%s" % (mods_value, final)


def translate_key_data(
    data: str, flags: int, application_mode: bool = False
) -> str:
    """
    Translate raw key data into the encoding for a pane with the given
    keyboard protocol flags.
    """
    items = _parse_key_data(data)
    return "".join(
        _encode_event(item, flags, application_mode)
        if isinstance(item, KeyEvent)
        else item
        for item in items
    )
