#!/usr/bin/env python3
"""Regenerate ICS calendar files from index.html EXT and OWN arrays."""

import re
import json
from datetime import date, timedelta

def parse_date_range(date_str, month):
    """Parse date string like '8/3–7', '8/12–13', '9/22', '8–9月', '6–7月（TBC）'."""
    date_str = date_str.strip()

    # Try single date like "9/22" or "4/24"
    m = re.match(r'^(\d+)/(\d+)$', date_str)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        start = date(2026, mo, d)
        end = start + timedelta(days=1)
        return start, end

    # Try range like "8/3–7" or "8/12–13" or "4/20–23"
    m = re.match(r'^(\d+)/(\d+)[–\-](\d+)$', date_str)
    if m:
        mo, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = date(2026, mo, d1)
        end = date(2026, mo, d2) + timedelta(days=1)
        return start, end

    # Try range across months like "5/28–5/29"
    m = re.match(r'^(\d+)/(\d+)[–\-](\d+)/(\d+)$', date_str)
    if m:
        m1, d1, m2, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        start = date(2026, m1, d1)
        end = date(2026, m2, d2) + timedelta(days=1)
        return start, end

    # Try "6/2–5" style (already covered above but let's be safe with the dash)
    m = re.match(r'^(\d+)/(\d+)[–\-–](\d+)$', date_str)
    if m:
        mo, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = date(2026, mo, d1)
        end = date(2026, mo, d2) + timedelta(days=1)
        return start, end

    # Fallback: use just the month
    try:
        start = date(2026, month, 1)
        end = start + timedelta(days=1)
        return start, end
    except Exception:
        return None, None


def parse_js_array(js_text, var_name):
    """
    Extract and loosely parse a JS array from the page.
    Returns list of dict-like objects as strings, then eval with json tricks.
    """
    # Find the array definition
    pattern = rf'const {var_name}=\[(.*?)\];\s*\n'
    m = re.search(pattern, js_text, re.DOTALL)
    if not m:
        return []
    array_str = m.group(1)

    # Parse individual objects using a state machine approach
    objects = []
    depth = 0
    start = None
    for i, ch in enumerate(array_str):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                obj_str = array_str[start:i+1]
                obj = parse_js_object(obj_str)
                if obj:
                    objects.append(obj)
                start = None
    return objects


def parse_js_object(s):
    """Parse a JS object literal into a Python dict (best effort)."""
    result = {}
    # Remove outer braces
    s = s.strip()
    if s.startswith('{'):
        s = s[1:]
    if s.endswith('}'):
        s = s[:-1]

    # Extract key:value pairs, handling arrays and nested strings
    i = 0
    while i < len(s):
        # Skip whitespace
        while i < len(s) and s[i] in ' \t\n\r':
            i += 1
        if i >= len(s):
            break

        # Read key
        key_start = i
        while i < len(s) and s[i] not in ':':
            i += 1
        key = s[key_start:i].strip().strip('"\'')
        i += 1  # skip ':'

        # Skip whitespace
        while i < len(s) and s[i] in ' \t\n\r':
            i += 1
        if i >= len(s):
            break

        # Read value
        ch = s[i]
        if ch == '"':
            # String value
            i += 1
            val_chars = []
            while i < len(s):
                c = s[i]
                if c == '\\' and i+1 < len(s):
                    val_chars.append(s[i+1])
                    i += 2
                elif c == '"':
                    i += 1
                    break
                else:
                    val_chars.append(c)
                    i += 1
            val = ''.join(val_chars)
        elif ch == '[':
            # Array value
            depth = 0
            val_start = i
            while i < len(s):
                if s[i] == '[':
                    depth += 1
                elif s[i] == ']':
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            arr_str = s[val_start:i]
            # Parse array of strings
            val = re.findall(r'"((?:[^"\\]|\\.)*)"', arr_str)
        elif ch in 'tfTF':
            # Boolean
            if s[i:i+4].lower() == 'true':
                val = True
                i += 4
            elif s[i:i+5].lower() == 'false':
                val = False
                i += 5
            else:
                val = None
                while i < len(s) and s[i] not in ',\n':
                    i += 1
        elif ch.isdigit() or ch == '-':
            val_start = i
            while i < len(s) and s[i] not in ',\n}':
                i += 1
            try:
                val = int(s[val_start:i].strip())
            except ValueError:
                val = s[val_start:i].strip()
        else:
            # Unquoted or unknown, read until comma
            val_start = i
            while i < len(s) and s[i] not in ',\n':
                i += 1
            val = s[val_start:i].strip()

        result[key] = val

        # Skip comma
        while i < len(s) and s[i] in ' \t\n\r,':
            i += 1

    return result


def make_ics(events, cal_name, cal_desc, filename):
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Siraya Tech//Siraya Activities 2026//ZH',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:{cal_name}',
        'X-WR-TIMEZONE:Asia/Taipei',
        f'X-WR-CALDESC:{cal_desc}',
    ]

    uid_counter = 1
    for ev in events:
        month = ev.get('m', 1)
        if not isinstance(month, int):
            try:
                month = int(month)
            except Exception:
                month = 1

        date_str = ev.get('date', '')
        start, end = parse_date_range(date_str, month)

        if start is None:
            start = date(2026, month, 1)
            end = start + timedelta(days=1)

        note = ev.get('note', '')
        # Escape commas and backslashes for ICS
        note = note.replace('\\', '\\\\').replace(',', '\\,').replace('\n', '\\n')

        uid = f'siraya-2026-{uid_counter}@sirayatech.com'
        uid_counter += 1

        ev_lines = [
            'BEGIN:VEVENT',
            f'DTSTART;VALUE=DATE:{start.strftime("%Y%m%d")}',
            f'DTEND;VALUE=DATE:{end.strftime("%Y%m%d")}',
            f'SUMMARY:{ev.get("name", "")}',
            f'LOCATION:{ev.get("loc", "")}',
            f'DESCRIPTION:{note}',
        ]

        ind = ev.get('ind', '')
        if isinstance(ind, list):
            ev_lines.append(f'CATEGORIES:{",".join(ind)}')
        else:
            ev_lines.append(f'CATEGORIES:{ind}')

        ev_lines.append(f'UID:{uid}')
        ev_lines.append('DTSTAMP:20260522T000000Z')

        url = ev.get('url', '')
        if url and url != '#':
            ev_lines.append(f'URL:{url}')

        ev_lines.append('END:VEVENT')
        lines.extend(ev_lines)

    lines.append('END:VCALENDAR')
    content = '\r\n'.join(lines) + '\r\n'

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'Written {filename} ({uid_counter - 1} events)')


def main():
    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # Extract the script section
    script_m = re.search(r'<script>(.*?)</script>', html, re.DOTALL)
    if not script_m:
        print('Could not find script section')
        return
    js = script_m.group(1)

    ext_events = parse_js_array(js, 'EXT')
    own_events = parse_js_array(js, 'OWN')

    print(f'Parsed {len(ext_events)} EXT events, {len(own_events)} OWN events')

    all_events = ext_events + own_events

    def has_ind(ev, ind_val):
        ind = ev.get('ind', '')
        if isinstance(ind, list):
            return ind_val in ind
        return ind == ind_val

    igaming_events = [e for e in all_events if has_ind(e, 'iGaming')]
    web3_events = [e for e in all_events if has_ind(e, 'Web3')]
    ai_events = [e for e in all_events if has_ind(e, 'AI企業')]

    make_ics(all_events, 'Siraya 活動總覽 2026', '全部活動', 'cal.ics')
    make_ics(igaming_events, 'Siraya iGaming 活動 2026', 'iGaming 活動', 'igaming.ics')
    make_ics(web3_events, 'Siraya Web3 活動 2026', 'Web3 活動', 'web3.ics')
    make_ics(ai_events, 'Siraya AI企業 活動 2026', 'AI企業 活動', 'ai.ics')


if __name__ == '__main__':
    main()
