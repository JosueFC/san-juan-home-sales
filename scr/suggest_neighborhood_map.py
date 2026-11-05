"""Suggest merges for neighborhood names that look like variants of the same place.

Run from the repo root (after build_db.py):
    python scr/suggest_neighborhood_map.py [--db data/processed/san_juan_sales.db] [--out data/neighborhood_map_suggested.csv]

Within each municipality it links names that:
  * match after ignoring case, accents, punctuation and filler words (Ward, Sector, Urb., de, del, la ...)  -> exact_key
  * are very similar spellings (difflib ratio >= 0.90)                                                       -> similar
  * equal the first part of a comma name ("Pacifica, Encantada" and "Pacifica")                              -> first_part
The most frequent spelling in each group becomes the suggested clean name.

REVIEW THE OUTPUT. Delete rows you disagree with, then save the file as data/neighborhood_map.csv and rerun build_db.py.
Prints counts and place names only (no addresses or people).
"""
import argparse
import csv
import difflib
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

FILLER = {'ward', 'sector', 'urb', 'urbanizacion', 'barrio', 'bo', 'comunidad', 'de', 'del', 'la', 'las', 'los', 'el', 'y'}


def key(name):
    text = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    return ' '.join(t for t in re.sub(r'[^a-z0-9]+', ' ', text).split() if t not in FILLER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/processed/san_juan_sales.db')
    ap.add_argument('--out', default='data/neighborhood_map_suggested.csv')
    ap.add_argument('--threshold', type=float, default=0.90)
    ap.add_argument('--min-sales', type=int, default=8, help='sales needed to count a neighborhood as usable in the summary')
    args = ap.parse_args()
    con = sqlite3.connect(args.db)

    rows = con.execute(
        "SELECT m.name, n.name_raw, COUNT(*), SUM(a.property_id IS NOT NULL) "
        "FROM sales s JOIN neighborhood n USING (neighborhood_id) JOIN municipality m USING (municipality_id) "
        "LEFT JOIN analysis_sales a USING (property_id) GROUP BY n.neighborhood_id").fetchall()
    by_muni = defaultdict(list)
    for muni, raw, total, used in rows:
        by_muni[muni].append({'raw': raw, 'total': total, 'used': used or 0, 'key': key(raw),
                              'first': key(raw.split(',')[0])})

    out, merges = [], 0
    usable_before = sum(r['used'] >= args.min_sales for rs in by_muni.values() for r in rs)
    usable_after = 0
    group_no = 0
    for muni, items in sorted(by_muni.items()):
        parent = list(range(len(items)))
        link = {}

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j, kind):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri
            link[i] = link.get(i) or kind
            link[j] = link.get(j) or kind
            # keep the weakest evidence for the group
            order = {'exact_key': 0, 'similar': 1, 'first_part': 2}
            for x in (i, j):
                if order[kind] > order[link[x]]:
                    link[x] = kind

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if not a['key'] or not b['key']:
                    continue
                if a['key'] == b['key']:
                    union(i, j, 'exact_key')
                elif difflib.SequenceMatcher(None, a['key'], b['key']).ratio() >= args.threshold:
                    union(i, j, 'similar')
                elif (',' in a['raw'] and a['first'] == b['key']) or (',' in b['raw'] and b['first'] == a['key']):
                    union(i, j, 'first_part')

        groups = defaultdict(list)
        for i in range(len(items)):
            groups[find(i)].append(i)
        for members in groups.values():
            used_total = sum(items[i]['used'] for i in members)
            if len(members) == 1:
                usable_after += items[members[0]]['used'] >= args.min_sales
                continue
            usable_after += used_total >= args.min_sales
            canon = max(members, key=lambda i: (items[i]['total'], len(items[i]['raw'])))
            clean = ' '.join(items[canon]['raw'].split()).title()
            group_no += 1
            merges += len(members) - 1
            for i in sorted(members, key=lambda i: -items[i]['total']):
                it = items[i]
                out.append({'municipality': muni, 'raw': it['raw'], 'clean': clean,
                            'sales_all': it['total'], 'sales_analysis': it['used'],
                            'similarity': round(difflib.SequenceMatcher(None, it['key'], items[canon]['key']).ratio(), 2),
                            'link_type': link.get(i, 'canonical'), 'group': group_no})

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['municipality', 'raw', 'clean', 'sales_all', 'sales_analysis', 'similarity', 'link_type', 'group']
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)

    total_names = len(rows)
    print(f'Neighborhood names: {total_names} | groups to merge: {group_no} | names that would disappear: {merges}')
    print(f'Neighborhoods with {args.min_sales}+ analysis sales: {usable_before} now -> {usable_after} if all suggestions are accepted')
    print('\nBiggest groups (clean name | municipality | variants | analysis sales):')
    sizes = defaultdict(lambda: [0, 0, '', ''])
    for r in out:
        g = sizes[r['group']]
        g[0] += 1; g[1] += r['sales_analysis']; g[2] = r['clean']; g[3] = r['municipality']
    for g in sorted(sizes.values(), key=lambda g: -g[1])[:12]:
        print(f'  {g[2]} | {g[3]} | {g[0]} variants | {g[1]} sales')
    print(f'\nWrote {len(out)} rows to {path}. Review it, then save as data/neighborhood_map.csv and rerun build_db.py.')


if __name__ == '__main__':
    main()
