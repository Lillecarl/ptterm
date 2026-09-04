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

Three parts of a key event need a terminal that speaks the protocol:
the event type (press, repeat or release), the other codes of the key
(the shifted key and the key of the base layout), and the text that
the key writes. What such a terminal sends passes through to a pane
that asked for it, and goes away for a pane that did not.

All three are served for a legacy terminal as well, as far as it can:

- The text of a printable key needs nothing. The character that the
  terminal sends is that text.
- A key release is made up. The legacy encoding says that a key went
  down and never that it came up, so a key answers with a press and a
  release at once. The pane reads every key going down and coming up;
  only the time between the two is lost. `translate_key_data` takes
  `synthesize=False` to leave that off.
- The shifted key of a letter is the letter. Which key gives an
  exclamation mark depends on the layout of the user, and that the
  legacy encoding does not carry, so such a key reports no other code.
  kitty reports none either for a key that has none.

The forms follow the encoder of kitty (`kitty/key_encoding.c`), so a
pane sees what a real kitty gives it.
"""
from typing import List, NamedTuple, Optional, Sequence, Tuple, Union

__all__ = ["translate_key_data"]


# Modifier bits. (The encoded value in a CSI u sequence is one plus the
# sum of the set bits.)
_SHIFT = 1
_ALT = 2
_CTRL = 4

# Keyboard protocol flags. (BetterScreen.kitty_keyboard_flags.)
_DISAMBIGUATE = 0b1
_REPORT_EVENT_TYPES = 0b10
_REPORT_ALTERNATE_KEYS = 0b100
_REPORT_ALL_KEYS = 0b1000
_REPORT_ASSOCIATED_TEXT = 0b10000

# Event types. (The encoded value is the one below.)
_PRESS = 1
_REPEAT = 2
_RELEASE = 3

# Final bytes of the "CSI 1 ; modifier <letter>" functional key form.
_LETTER_FINALS = "ABCDEFHPQS"


class KeyEvent(NamedTuple):
    "One decoded key event, in the terms of the keyboard protocol."
    code: int  # unicode key code, or the number of the CSI form
    mods: int  # shift/alt/ctrl bitmask (without the +1 offset)
    final: str  # "u", "~" or one of _LETTER_FINALS
    text: str = ""  # reported text, if the terminal sent it
    #: The other codes of the key: the shifted key, then the key of the
    #: base layout. Only a terminal that speaks the protocol sends
    #: them, and it leaves a slot empty when it has nothing for it, so
    #: a slot holds None. Nothing reconstructs these from legacy data:
    #: which key gives a character depends on the layout of the user.
    alternates: Tuple[Optional[int], ...] = ()
    #: Press, repeat or release. Legacy data holds presses only.
    event: int = _PRESS


# Parse result items: KeyEvent, or a str to pass through verbatim
# (opaque sequences like device attribute replies).
_Item = Union[KeyEvent, str]


def _split_slots(part: str) -> List[Optional[int]]:
    """
    Split one parameter into its subparameters, keeping the empty ones.

    "97:65" gives [97, 65] and "97::99" gives [97, None, 99]. An empty
    slot means the default of that slot, and the position carries the
    meaning, so it may not collapse.
    """
    return [int(x) if x else None for x in part.split(":")]


def _first(slots: Sequence[Optional[int]], default: int) -> int:
    "The first slot of a parameter, or the default when it is empty."
    if slots and slots[0] is not None:
        return slots[0]
    return default


def _trimmed(slots: Sequence[Optional[int]]) -> Tuple[Optional[int], ...]:
    "The slots without the empty ones at the end. They mean nothing."
    kept = list(slots)
    while kept and kept[-1] is None:
        kept.pop()
    return tuple(kept)


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
    # A printable character is the text of its own key event. A pane
    # that asks for the text of a key gets it that way, also from a
    # terminal that speaks the legacy encoding only.
    lower = char.lower()
    if char.isupper() and lower != char and len(lower) == 1:
        # The shifted key of a letter is the letter, so a pane that
        # asks for the other codes of a key gets that one. The key of
        # the base layout stays empty: kitty leaves it out for a
        # layout where it is the key itself, which is every Latin one.
        return KeyEvent(ord(lower), _SHIFT, "u", char, (code,))
    if char.isprintable():
        return KeyEvent(code, 0, "u", char)
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

    # The full form of a key event is
    # "CSI code:shifted:base ; mods:event ; text final".
    rows = [_split_slots(part) for part in params.split(";")] if params else []
    keys = rows[0] if rows else []
    modifiers = rows[1] if len(rows) > 1 else []
    mods = max(0, _first(modifiers, 1) - 1)
    event = modifiers[1] if len(modifiers) > 1 and modifiers[1] else _PRESS
    alternates = _trimmed(keys[1:])

    if final in ("u", "~") or final in _LETTER_FINALS:
        # A key of the letter form carries no code of its own: the
        # first parameter is the one of the sequence, and it is one.
        code = _first(keys, 1 if final in _LETTER_FINALS else 0)
        text = (
            "".join(chr(n) for n in rows[2] if n) if len(rows) > 2 else ""
        )
        return (
            KeyEvent(code, mods, final, text, alternates, event),
            i + 1 - start,
        )

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


def _serialize(
    code: int,
    mods_value: int,
    final: str,
    alternates: Tuple[Optional[int], ...] = (),
    event: int = _PRESS,
    text: str = "",
) -> str:
    """
    Write one key event in the escape code form of the protocol.

    The form is "CSI code:shifted:base ; mods:event ; text final". A
    field that holds its default stays empty, and a field at the end
    that holds its default is left out. This follows the encoder of
    kitty, so that a pane sees what a real kitty gives it.
    """
    second = mods_value != 1 or event != _PRESS
    third = bool(text)

    out = "\x1b["
    if code != 1 or alternates or second or third:
        out += str(code)
    if alternates:
        out += ":" + ":".join(
            "" if slot is None else str(slot) for slot in alternates
        )
    if second or third:
        out += ";"
        if mods_value != 1:
            out += str(mods_value)
        if event != _PRESS:
            out += ":%d" % event
    if third:
        out += ";" + ":".join(str(ord(char)) for char in text)
    return out + final


#: Keys that the legacy encoding writes as one control character. A
#: release of one of them has no legacy form, and kitty reports it only
#: when the pane asks for all keys as escape codes.
_CONTROL_CODES = (13, 9, 127)


def _encode_event(event: KeyEvent, flags: int, application_mode: bool) -> str:
    "Encode a key event for a pane with the given protocol flags."
    code, mods, final, text, alternates, kind = event
    mods_value = mods + 1

    # Only a pane that asked for the event types can read a release. A
    # repeat without that flag is a press: that is what the key did.
    if kind == _RELEASE and not flags & _REPORT_EVENT_TYPES:
        return ""
    if not flags & _REPORT_EVENT_TYPES:
        kind = _PRESS
    if kind == _RELEASE and mods == 0 and code in _CONTROL_CODES:
        if not flags & _REPORT_ALL_KEYS:
            return ""
    if not flags & _REPORT_ALTERNATE_KEYS or final != "u":
        # kitty sends the other codes of a key for the "u" form only.
        alternates = ()
    embedded = text if flags & _REPORT_ASSOCIATED_TEXT else ""

    if final == "u":
        ambiguous = bool(mods & (_CTRL | _ALT)) or code == 27
        if (
            flags & _REPORT_ALL_KEYS
            or (flags & _DISAMBIGUATE and ambiguous)
            or kind != _PRESS
            or alternates
            or embedded
        ):
            return _serialize(
                code, mods_value, "u", alternates, kind, embedded
            )

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
        return char

    if final == "~":
        return _serialize(code, mods_value, "~", (), kind, embedded)

    # Functional keys with a letter final byte.
    if mods == 0 and kind == _PRESS and not embedded:
        if not flags & _REPORT_ALL_KEYS:
            if application_mode and final in "ABCD":
                return "\x1bO" + final
            if final in "PQRS":
                return "\x1bO" + final
        return "\x1b[" + final
    return _serialize(code, mods_value, final, (), kind, embedded)


def translate_key_data(
    data: str,
    flags: int,
    application_mode: bool = False,
    source_flags: int = 0,
    synthesize: bool = True,
) -> str:
    """
    Translate raw key data into the encoding for a pane with the given
    keyboard protocol flags.

    `source_flags` says what the terminal that sends the keys reports,
    in the same flags. A terminal that reports the event types sends a
    release of its own, and the release passes through.

    `synthesize` says what to do when that terminal reports no event
    type and the pane asked for one. With it, a key answers with a
    press and a release at once: the pane then reads every key it went
    down and came up, and only the time between the two is lost. That
    is what a pane asked for, and no terminal can do better than the
    keyboard it has. Without it, the pane hears that it has no event
    types (see `BetterScreen.deliverable_kitty_keyboard_flags`) and
    reads presses only.
    """
    # The release of a key that the terminal never reports coming up.
    double = bool(
        synthesize
        and flags & _REPORT_EVENT_TYPES
        and not source_flags & _REPORT_EVENT_TYPES
    )

    parts = []
    for item in _parse_key_data(data):
        if not isinstance(item, KeyEvent):
            parts.append(item)
            continue
        parts.append(_encode_event(item, flags, application_mode))
        if double and item.event == _PRESS:
            parts.append(
                _encode_event(
                    item._replace(event=_RELEASE), flags, application_mode
                )
            )
    return "".join(parts)
