#!/usr/bin/env python3
"""Semantic search for WHUT knowledge base.
Zero external deps beyond numpy. Uses TF-IDF with char n-grams over document CHUNKS.

Usage:
  python3 search/kb_semantic.py build           # Pre-compute TF-IDF index (chunked)
  python3 search/kb_semantic.py search <query>   # Search with similarity ranking
"""
import sys, os, glob, json, math, re, pickle
from collections import Counter

import numpy as np

KB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "knowledge")
INDEX_FILE = os.path.join(KB, "semantic_index.pkl")
CACHE_FILE = os.path.join(KB, "semantic_cache.npz")

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def tokenize(text: str) -> list:
    """Character n-gram tokenizer for Chinese + English."""
    tokens = []
    chars = text.lower()
    n = len(chars)
    for i in range(n - 1):
        seg = chars[i:i+2]
        if any(ord(c) > 127 for c in seg):
            tokens.append(seg)
    for i in range(n - 2):
        seg = chars[i:i+3]
        if any(ord(c) > 127 for c in seg):
            tokens.append(seg)
    for word in re.findall(r'[a-zA-Z0-9_]+', text):
        tokens.append("__w_" + word.lower() + "__")
    return tokens


def _load_files(kb_path=None):
    """Load all KB files. Returns list of (topic, text)."""
    if kb_path is None:
        kb_path = KB
    files = sorted(glob.glob(os.path.join(kb_path, "*.md")))
    docs = []
    for fp in files:
        fname = os.path.basename(fp).replace(".md", "")
        if fname == "index":
            continue
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        docs.append((fname, text))
    return docs


def _chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping character chunks."""
    chunks = []
    n = len(text)
    step = size - overlap
    start = 0
    while start < n:
        chunks.append(text[start:start+size])
        if start + size >= n:
            break
        start += step
    if not chunks:
        chunks = [text]
    return chunks


def build_index(kb_path=None):
    """Build chunked TF-IDF index and save to cache files."""
    if kb_path is None:
        kb_path = KB
    docs = _load_files(kb_path)
    if not docs:
        print("[semantic] No documents found")
        return

    chunk_stems = []   # file stem per chunk
    chunk_texts = []   # text per chunk
    chunk_tokens = []  # Counter per chunk
    doc_freq = Counter()

    for fname, text in docs:
        for ch in _chunk_text(text):
            toks = tokenize(ch)
            chunk_stems.append(fname)
            chunk_texts.append(ch)
            chunk_tokens.append(Counter(toks))
            for term in set(toks):
                doc_freq[term] += 1

    n_chunks = len(chunk_stems)
    n_docs = len(docs)
    print("[semantic] Indexing %d documents, %d chunks..." % (n_docs, n_chunks))

    vocab = {}
    for term, df in doc_freq.items():
        if 2 <= df <= n_chunks - 1:
            vocab[term] = len(vocab)
    n_vocab = len(vocab)

    idf_values = {term: math.log((n_chunks + 1) / (df + 1)) + 1 for term, df in doc_freq.items()}

    rows, cols, values = [], [], []
    doc_norms = np.zeros(n_chunks)
    for i, tf_counter in enumerate(chunk_tokens):
        total_terms = sum(tf_counter.values()) or 1
        for term, tf in tf_counter.items():
            if term in vocab:
                j = vocab[term]
                tf_idf = (tf / total_terms) * idf_values[term]
                rows.append(i)
                cols.append(j)
                values.append(tf_idf)
                doc_norms[i] += tf_idf * tf_idf
    doc_norms = np.sqrt(doc_norms)

    np.savez_compressed(
        CACHE_FILE,
        rows=np.array(rows, dtype=np.int32),
        cols=np.array(cols, dtype=np.int32),
        values=np.array(values, dtype=np.float32),
        doc_norms=doc_norms.astype(np.float32),
        n_chunks=np.array(n_chunks, dtype=np.int32),
        n_vocab=np.array(n_vocab, dtype=np.int32),
    )

    with open(INDEX_FILE, "wb") as f:
        pickle.dump({
            "vocab": vocab,
            "idf": {t: idf_values[t] for t in vocab},
            "file_stems": sorted(set(chunk_stems)),
            "n_docs": n_docs,
            "chunk_info": list(zip(chunk_stems, chunk_texts)),
        }, f)
    print("[semantic] Index saved: %d bytes + %d bytes" % (
        os.path.getsize(CACHE_FILE), os.path.getsize(INDEX_FILE)))


_INDEX_CACHE = {"key": None, "meta": None, "doc_vectors": None, "doc_norms": None, "n_vocab": None}


def load_index():
    if not os.path.exists(CACHE_FILE) or not os.path.exists(INDEX_FILE):
        return None, None, None, None
    key = (os.path.getmtime(INDEX_FILE), os.path.getmtime(CACHE_FILE))
    if _INDEX_CACHE["key"] == key and _INDEX_CACHE["meta"] is not None:
        return (_INDEX_CACHE["meta"], _INDEX_CACHE["doc_vectors"],
                _INDEX_CACHE["doc_norms"], _INDEX_CACHE["n_vocab"])
    npz = np.load(CACHE_FILE)
    with open(INDEX_FILE, "rb") as f:
        meta = pickle.load(f)
    n_chunks = int(npz["n_chunks"])
    doc_vectors = [{} for _ in range(n_chunks)]
    for r, c, v in zip(npz["rows"], npz["cols"], npz["values"]):
        doc_vectors[r][c] = v
    _INDEX_CACHE["key"] = key
    _INDEX_CACHE["meta"], _INDEX_CACHE["doc_vectors"] = meta, doc_vectors
    _INDEX_CACHE["doc_norms"], _INDEX_CACHE["n_vocab"] = npz["doc_norms"], int(npz["n_vocab"])
    return (_INDEX_CACHE["meta"], _INDEX_CACHE["doc_vectors"],
            _INDEX_CACHE["doc_norms"], _INDEX_CACHE["n_vocab"])


def search(query, top_k=10):
    """Search with TF-IDF cosine over chunks, aggregated per document.
    Returns [(file_stem, max_sim, best_chunk_text), ...]"""
    meta, doc_vectors, doc_norms, n_vocab = load_index()
    if meta is None:
        print("[semantic] Index not found. Run 'python3 search/kb_semantic.py build' first")
        return []
    vocab = meta["vocab"]
    idf = meta["idf"]
    chunk_info = meta["chunk_info"]
    n_chunks = len(chunk_info)

    query_tokens = tokenize(query)
    query_tf = Counter(query_tokens)
    total_terms = sum(query_tf.values()) or 1
    query_vec = {}
    query_norm = 0.0
    for term, tf in query_tf.items():
        if term in vocab:
            j = vocab[term]
            tf_idf = (tf / total_terms) * idf.get(term, 1)
            query_vec[j] = tf_idf
            query_norm += tf_idf * tf_idf
    query_norm = math.sqrt(query_norm)
    if query_norm == 0:
        return []

    chunk_scores = []
    for i in range(n_chunks):
        if doc_norms[i] == 0:
            continue
        dot = 0.0
        for term_id, q_val in query_vec.items():
            if term_id in doc_vectors[i]:
                dot += q_val * doc_vectors[i][term_id]
        if dot > 0:
            sim = dot / (query_norm * doc_norms[i])
            chunk_scores.append((chunk_info[i][0], sim, chunk_info[i][1]))

    if not chunk_scores:
        return []

    best = {}
    for stem, sim, text in chunk_scores:
        if stem not in best or sim > best[stem][0]:
            best[stem] = (sim, text)
    results = sorted(best.items(), key=lambda kv: -kv[1][0])

    return [(stem, sim, text[:500]) for stem, (sim, text) in results[:top_k]]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "build":
        build_index()
    elif cmd == "search" and len(sys.argv) >= 3:
        res = search(" ".join(sys.argv[2:]))
        for stem, sim, sn in res:
            print("%.3f %s: %s" % (sim, stem, sn[:60].replace("\n", " ")))
    else:
        print("Usage: python3 search/kb_semantic.py build|search <query>")
