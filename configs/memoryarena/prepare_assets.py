"""Pinned optional assets and the smallest complete Math sample (no model calls)."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path

REFERENCE_REVISION = "6cd9de14b71915e39ac742a20dc33785e14b6aab"
DATASET_REVISION = "da1a37c8b19280e18627ca01cf368195a5e1d92e"
PRODUCT_REVISION = "46120a5c931d04a47bd791965d757207b7372b62"
CORPUS_REVISION = "b27b02bc3e45511b8b82a13e6f90ce761df726f6"
TOKENIZER_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"
FLIGHT_URL = "https://drive.usercontent.google.com/download?id=1dNtxHFv7k0PeMHI0smZk8t-dBlWLA0Gz&export=download&confirm=t"
FLIGHT_SHA256 = "8dafdb0e3f8b79ce599a1e612a772865295bc226b46e5fb278368f7255b11cee"


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def math_sample(root: Path) -> dict:
    from datasets import load_dataset

    rows = load_dataset(
        "ZexueHe/memoryarena", "formal_reasoning_math", split="test", revision=DATASET_REVISION
    )
    row = min((r for r in rows if len(r["questions"]) >= 2), key=lambda r: (len(r["questions"]), r["id"]))
    target = root / "math-complete-sample.json"
    write_json(target, [row])
    return {
        "source": "ZexueHe/memoryarena",
        "revision": DATASET_REVISION,
        "selection": "fewest complete rounds >= 2, then smallest id; independent of answers and agent performance",
        "id": row["id"],
        "rounds": len(row["questions"]),
        "path": str(target),
        "sha256": sha256(target),
    }


def travel(root: Path, reference: Path) -> dict:
    import requests

    revision = subprocess.check_output(["git", "-C", str(reference), "rev-parse", "HEAD"], text=True).strip()
    if revision != REFERENCE_REVISION:
        raise ValueError("Travel database requires the pinned MemoryArena checkout")
    source = reference / "env/env_systems/travel_planner_env/database"
    target = root / "travel/database"
    shutil.copytree(source, target, dirs_exist_ok=True)
    flights = target / "flights/clean_Flights_2022.csv"
    if not flights.exists() or sha256(flights) != FLIGHT_SHA256:
        flights.parent.mkdir(parents=True, exist_ok=True)
        partial = flights.with_suffix(".csv.part")
        with requests.get(FLIGHT_URL, stream=True, timeout=120) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for block in response.iter_content(1024 * 1024):
                    handle.write(block)
        if sha256(partial) != FLIGHT_SHA256:
            raise ValueError("Flight download does not match the pinned CSV checksum")
        partial.replace(flights)
    return {
        "url": FLIGHT_URL,
        "source_revision": revision,
        "path": str(target),
        "flights_sha256": sha256(flights),
    }


def shopping(root: Path, limit: int | None) -> dict:
    from huggingface_hub import snapshot_download

    target = root / "shopping"
    snapshot_download(
        "ai-hyz/MemoryArena-product-db",
        repo_type="dataset",
        revision=PRODUCT_REVISION,
        local_dir=target,
        allow_patterns=[
            "items_shuffle.json",
            "items_ins_v2.json",
            "domain_data.json",
            "product_catalog/*.json",
            "search_engine/indexes-full/*",
        ],
        max_workers=3,
    )
    result = {"source": "ai-hyz/MemoryArena-product-db", "revision": PRODUCT_REVISION, "path": str(target)}
    if limit:
        import ijson

        with (target / "items_shuffle.json").open("rb") as handle:
            products = list(itertools.islice(ijson.items(handle, "item", use_float=True), limit))
        subset = target / f"items-first{limit}-smoke.json"
        subset.write_text(json.dumps(products, ensure_ascii=False), encoding="utf-8")
        result["transport_only_subset"] = {
            "path": str(subset),
            "products": len(products),
            "sha256": sha256(subset),
        }
    return result


def search(root: Path, worker: str | None, java_home: str | None) -> dict:
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    if not worker:
        raise ValueError("Search preparation requires --worker-python (the optional Pyserini worker)")
    corpus = root / "search-corpus"
    snapshot_download(
        "Tevatron/browsecomp-plus-corpus",
        repo_type="dataset",
        revision=CORPUS_REVISION,
        local_dir=corpus,
        allow_patterns=["data/*.parquet", "README.md"],
        max_workers=3,
    )
    cache = root / "search-tokenizer-cache/hub"
    snapshot = snapshot_download(
        "Qwen/Qwen3-0.6B",
        revision=TOKENIZER_REVISION,
        cache_dir=cache,
        allow_patterns=[
            "config.json",
            "tokenizer*",
            "vocab.json",
            "merges.txt",
            "special_tokens_map.json",
            "chat_template*",
        ],
    )
    ref = cache / "models--Qwen--Qwen3-0.6B/refs/main"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text(TOKENIZER_REVISION, encoding="utf-8")
    exported = root / "search-jsonl"
    exported.mkdir(exist_ok=True)
    count = 0
    for source in sorted((corpus / "data").glob("*.parquet")):
        output = exported / (source.stem + ".jsonl")
        with output.open("w", encoding="utf-8") as handle:
            for batch in pq.ParquetFile(source).iter_batches(batch_size=128):
                for row in batch.to_pylist():
                    handle.write(
                        json.dumps(
                            {"id": str(row["docid"]), "contents": row["text"], "url": row["url"]},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    count += 1
    environment = dict(os.environ)
    environment["JAVA_TOOL_OPTIONS"] = "-Xmx1536m -Dfile.encoding=UTF-8"
    if java_home:
        environment.update(
            JAVA_HOME=java_home, PATH=str(Path(java_home) / "bin") + os.pathsep + environment["PATH"]
        )
    index = root / "search-bm25-utf8"
    if not list(index.glob("segments_*")):
        command = [
            worker,
            "-m",
            "pyserini.index.lucene",
            "--collection",
            "JsonCollection",
            "--input",
            str(exported),
            "--index",
            str(index),
            "--generator",
            "DefaultLuceneDocumentGenerator",
            "--threads",
            "2",
            "--storeRaw",
            "--storePositions",
            "--storeDocvectors",
        ]
        with (root / "search-index-utf8.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    # Anserini can exit 0 after per-file errors; verify the document count explicitly.
    check = "import sys; from pyserini.search.lucene import LuceneSearcher; print(LuceneSearcher(sys.argv[1]).num_docs)"
    observed = (
        subprocess.check_output([worker, "-c", check, str(index)], env=environment, text=True)
        .strip()
        .splitlines()[-1]
    )
    if int(observed) != count or count != 100195:
        raise ValueError(
            f"Incomplete Search index: {observed} documents, expected {count}; use a fresh output directory"
        )
    return {
        "corpus_revision": CORPUS_REVISION,
        "document_count": count,
        "index": str(index),
        "tokenizer_revision": TOKENIZER_REVISION,
        "tokenizer_cache": str(cache),
        "tokenizer_snapshot": snapshot,
        "index_sha256": {p.name: sha256(p) for p in sorted(index.iterdir()) if p.is_file()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=["math", "travel", "shopping", "search"], required=True)
    parser.add_argument("--output", type=Path, default=Path(".cache/memoryarena-assets"))
    parser.add_argument("--reference", type=Path, default=Path(".cache/memoryarena"))
    parser.add_argument("--worker-python")
    parser.add_argument("--java-home")
    parser.add_argument("--shopping-smoke-limit", type=int)
    args = parser.parse_args()
    if args.shopping_smoke_limit is not None and args.shopping_smoke_limit < 1:
        parser.error("--shopping-smoke-limit must be positive")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(root / "hf-cache"))
    if args.scene == "math":
        result = math_sample(root)
    elif args.scene == "travel":
        result = travel(root, args.reference.resolve())
    elif args.scene == "shopping":
        result = shopping(root, args.shopping_smoke_limit)
    else:
        result = search(root, args.worker_python, args.java_home)
    manifest = root / f"{args.scene}-preparation-manifest.json"
    write_json(manifest, result)
    print(manifest)


if __name__ == "__main__":
    main()
