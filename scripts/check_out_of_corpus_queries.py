"""Diagnostic: check whether out-of-corpus queries produce a weak similarity gap.

One-off script backing the "코퍼스 범위 밖 질문" section of the eval log.
Queries are hardcoded on purpose — they document what was actually measured.
"""

import json, glob
import numpy as np
from sentence_transformers import SentenceTransformer

KEYS = ('배변', '소변', '대변', '오줌', '똥', '화장실', '패드')
QUERIES = [
    '배변 실수를 나중에 발견했어요. 어떻게 해야 하나요?',
    '애가 두살인데 배변실수를 어떻게 관리해?',
]

paths = sorted(glob.glob('data/processed/youtube/chunks/*.jsonl'))
print('chunk files:', len(paths))
rows = [json.loads(line) for p in paths for line in open(p, encoding='utf-8')]
print('total chunks:', len(rows))

hits = [r for r in rows if any(k in r['text'] for k in KEYS)]
print('배변 관련 청크:', len(hits))
for r in hits:
    print('  #', r['chunk_index'], r['chapter_title'][:30])

corpus = [r for r in rows if r['embedding_eligible']]
print('eligible:', len(corpus))

model = SentenceTransformer('intfloat/multilingual-e5-base')
mat = model.encode(['passage: ' + r['text'] for r in corpus], normalize_embeddings=True)

for q in QUERIES:
    vec = model.encode('query: ' + q, normalize_embeddings=True)
    scores = mat @ vec
    print()
    print('Q:', q)
    print('  mean:', round(float(scores.mean()), 4))
    for i in np.argsort(-scores)[:5]:
        row = corpus[i]
        print('  {:.4f}  #{}  {}'.format(scores[i], row['chunk_index'], row['chapter_title'][:26]))
