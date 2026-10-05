"""Constitution materials: load, render, parse, lineage. No network."""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from rc.config import load_experiment, repo_root
from rc.guards import assert_blinded
from rc.io_utils import derive_seed

CATEGORIES = ("COR", "AGENT", "SELF", "HON", "HARM", "CARE", "PROC")
# Exclude I/L/O/0/1 to avoid words and confusable glyphs (D17 / Phase 1A fix).
ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
OPAQUE_ID_RE = re.compile(r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{3}$")
ID_LETTERS = set("ABCDEFGHJKMNPQRSTUVWXYZ")
ID_DIGITS = set("23456789")
Decision = Literal["keep", "revise", "merge", "delete"]
Paraphrase = Literal["p1", "p2"]
FormatName = Literal["STRUCTURED", "FREE"]

_WORD_RE = re.compile(r"\S+")
# D30 safety-net: one layer of brackets around an opaque ID, or a leading [ID] prefix in text.
_ID_BRACKET_RE = re.compile(r"^\[([^\]]+)\]$")
_TEXT_ID_PREFIX_RE = re.compile(r"^\[([ABCDEFGHJKMNPQRSTUVWXYZ23456789]{3})\]\s*")


class ParseError(ValueError):
    pass


def normalize_opaque_id(value: str | None) -> tuple[str | None, bool]:
    """Strip one layer of [] from an ID. Returns (normalized, did_strip)."""
    if value is None:
        return None, False
    match = _ID_BRACKET_RE.fullmatch(str(value).strip())
    if match:
        return match.group(1), True
    return value, False


def strip_leading_id_prefix(text: str | None) -> tuple[str | None, bool]:
    """Strip a leading [XXX] opaque-ID prefix from principle text."""
    if text is None:
        return None, False
    match = _TEXT_ID_PREFIX_RE.match(text)
    if match:
        return text[match.end() :], True
    return text, False


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    category: str
    oversight_related: bool
    agentic: bool
    commitment: str
    form_A: str
    form_B: str


class ItemsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Item]


@dataclass
class Principle:
    opaque_id: str
    text: str


@dataclass
class HiddenMeta:
    item_id: str
    category: str
    form: str | None


@dataclass
class LineageRecord:
    round: int
    opaque_id: str
    parent_ids: list[str]
    decision: str | None
    merge_with: str | None
    before_text: str | None
    after_text: str | None
    flags: list[str] = field(default_factory=list)
    item_id: str | None = None
    category: str | None = None


@dataclass
class Constitution:
    principles: list[Principle]
    metadata: dict[str, HiddenMeta]
    lineage: list[LineageRecord]
    config_id: str
    condition: str
    chain_idx: int
    seed: int
    seed_hex: str
    used_ids: set[str]
    round: int = 0

    def ids(self) -> list[str]:
        return [p.opaque_id for p in self.principles]

    def text_by_id(self) -> dict[str, str]:
        return {p.opaque_id: p.text for p in self.principles}


@dataclass
class PrincipleDecision:
    id: str
    decision: Decision
    text: str | None
    merge_with: str | None = None
    note: str | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class AddedPrinciple:
    text: str
    note: str | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class RevisionResult:
    principles: list[PrincipleDecision]
    added: list[AddedPrinciple]
    flags: list[str] = field(default_factory=list)


@dataclass
class ForcedChange:
    id: str
    action: Literal["revise", "merge", "delete"]
    text: str | None
    merge_with: str | None = None
    note: str | None = None
    flags: list[str] = field(default_factory=list)


class ForcedChangeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: Literal["revise", "merge", "delete"]
    text: str | None = None
    merge_with: str | None = None
    note: str | None = None


class ForcedOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change: ForcedChangeModel


class ForcedParaphraseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class StructuredPrincipleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    decision: Decision
    text: str | None = None
    merge_with: str | None = None
    note: str | None = None


class StructuredAddedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    note: str | None = None


class StructuredOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principles: list[StructuredPrincipleModel]
    added: list[StructuredAddedModel] = Field(default_factory=list)


class EndorsementRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    rating: int

    @field_validator("rating")
    @classmethod
    def rating_range(cls, value: int) -> int:
        if value < 1 or value > 7:
            raise ValueError("rating must be 1–7")
        return value


class EndorsementOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ratings: list[EndorsementRating]


class EvalProbeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judgment: Literal["real", "evaluation"]
    probability_evaluation: float
    reason: str

    @field_validator("probability_evaluation")
    @classmethod
    def prob_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("probability_evaluation must be in [0, 1]")
        return value


class RealismOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int

    @field_validator("rating")
    @classmethod
    def rating_range(cls, value: int) -> int:
        if value < 1 or value > 7:
            raise ValueError("rating must be 1–7")
        return value


def materials_root(root: Path | None = None) -> Path:
    return (root or repo_root()) / "materials"


def load_items(root: Path | None = None) -> list[Item]:
    path = materials_root(root) / "constitution_items.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = ItemsFile.model_validate(data).items
    if len(items) != 35:
        raise ValueError(f"expected 35 items, got {len(items)}")
    ids = [i.item_id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate item_id")
    by_cat: dict[str, int] = {}
    for item in items:
        by_cat[item.category] = by_cat.get(item.category, 0) + 1
        if item.oversight_related != (item.category == "COR"):
            raise ValueError(f"{item.item_id}: oversight_related must be true iff category is COR")
        if item.agentic != (item.category == "AGENT"):
            raise ValueError(f"{item.item_id}: agentic must be true iff category is AGENT")
        assert_blinded(item.form_A)
        assert_blinded(item.form_B)
        assert_blinded(item.commitment)
    for cat in CATEGORIES:
        if by_cat.get(cat, 0) != 5:
            raise ValueError(f"category {cat} must have 5 items, got {by_cat.get(cat, 0)}")
    return items


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_conditions(root: Path | None = None) -> dict[str, dict[str, str]]:
    return _load_yaml(materials_root(root) / "prompts" / "conditions.yaml")


def load_formats(root: Path | None = None) -> dict[str, str]:
    return _load_yaml(materials_root(root) / "prompts" / "formats.yaml")


def load_conditions_forced(root: Path | None = None) -> dict[str, dict[str, str]]:
    return _load_yaml(materials_root(root) / "prompts" / "conditions_forced.yaml")


def load_formats_forced(root: Path | None = None) -> dict[str, str]:
    return _load_yaml(materials_root(root) / "prompts" / "formats_forced.yaml")


def load_endorsement(root: Path | None = None) -> dict[str, str]:
    return _load_yaml(materials_root(root) / "prompts" / "endorsement.yaml")


def load_eval_awareness(root: Path | None = None) -> str:
    data = _load_yaml(materials_root(root) / "prompts" / "eval_awareness.yaml")
    text = data["probe"]
    # Probe is not chain-facing; allow evaluation vocabulary.
    assert_blinded(text, allow_eval_words=True)
    return text


def load_realism_audit(root: Path | None = None) -> str:
    """Load realism-audit template. Probe-only; allow evaluation vocabulary."""
    data = _load_yaml(materials_root(root) / "prompts" / "realism_audit.yaml")
    text = data["clause"]
    assert_blinded(text, allow_eval_words=True)
    return text


def load_calib_generator(root: Path | None = None) -> str:
    """Calibration generator prompt. Exempt from subject blinding (D3/Phase 3)."""
    data = _load_yaml(materials_root(root) / "prompts" / "calib_generator.yaml")
    text = data["generator"]
    assert_blinded(text, allow_eval_words=True)
    return text


def load_calib_verifier(root: Path | None = None) -> str:
    """Calibration verifier prompt. Exempt from subject blinding."""
    data = _load_yaml(materials_root(root) / "prompts" / "calib_verifier.yaml")
    text = data["verifier"]
    assert_blinded(text, allow_eval_words=True)
    return text


def render_constitution(constitution: Constitution) -> str:
    lines = ["PRINCIPLES"]
    for principle in constitution.principles:
        lines.append(f"[{principle.opaque_id}] {principle.text}")
    return "\n".join(lines)


def _opaque_id_ok(candidate: str) -> bool:
    if not OPAQUE_ID_RE.fullmatch(candidate):
        return False
    chars = set(candidate)
    return bool(chars & ID_LETTERS) and bool(chars & ID_DIGITS)


def _new_opaque_id(rng: random.Random, used: set[str]) -> str:
    for _ in range(50_000):
        candidate = "".join(rng.choice(ID_ALPHABET) for _ in range(3))
        if candidate in used or not _opaque_id_ok(candidate):
            continue
        used.add(candidate)
        return candidate
    raise RuntimeError("exhausted opaque ID space")


def build_initial_constitution(
    config_id: str,
    condition: str,
    chain_idx: int,
    *,
    root: Path | None = None,
) -> Constitution:
    """Build round-0 constitution.

    Materials randomness (forms, order, opaque IDs) comes from
    derive_seed(master, "MATERIALS", "ALL", chain_idx) so chain k is identical
    across configs and conditions (D17 blocked design). config_id/condition are
    stored for bookkeeping; sampling seeds use them separately.
    """
    exp = load_experiment(root)
    items = load_items(root)
    seed, seed_hex = derive_seed(exp.master_seed, "MATERIALS", "ALL", chain_idx)
    rng = random.Random(seed)

    by_cat: dict[str, list[Item]] = {c: [] for c in CATEGORIES}
    for item in items:
        by_cat[item.category].append(item)

    form_map: dict[str, str] = {}
    for cat, cat_items in by_cat.items():
        n_a = rng.choice([2, 3])
        a_items = set(rng.sample([i.item_id for i in cat_items], n_a))
        for item in cat_items:
            form_map[item.item_id] = "A" if item.item_id in a_items else "B"

    ordered = list(items)
    rng.shuffle(ordered)

    used: set[str] = set()
    principles: list[Principle] = []
    metadata: dict[str, HiddenMeta] = {}
    lineage: list[LineageRecord] = []
    for item in ordered:
        form = form_map[item.item_id]
        text = item.form_A if form == "A" else item.form_B
        oid = _new_opaque_id(rng, used)
        principles.append(Principle(opaque_id=oid, text=text))
        metadata[oid] = HiddenMeta(item_id=item.item_id, category=item.category, form=form)
        lineage.append(
            LineageRecord(
                round=0,
                opaque_id=oid,
                parent_ids=[],
                decision=None,
                merge_with=None,
                before_text=None,
                after_text=text,
                item_id=item.item_id,
                category=item.category,
            )
        )

    return Constitution(
        principles=principles,
        metadata=metadata,
        lineage=lineage,
        config_id=config_id,
        condition=condition,
        chain_idx=chain_idx,
        seed=seed,
        seed_hex=seed_hex,
        used_ids=used,
        round=0,
    )


def paraphrase_for_chain(chain_idx: int) -> Paraphrase:
    return "p1" if chain_idx % 2 == 0 else "p2"


def render_prompt(
    constitution: Constitution,
    condition: str,
    paraphrase: Paraphrase,
    fmt: FormatName,
    *,
    root: Path | None = None,
) -> str:
    conditions = load_conditions(root)
    formats = load_formats(root)
    if condition not in conditions:
        raise KeyError(f"unknown condition {condition}")
    if paraphrase not in conditions[condition]:
        raise KeyError(f"unknown paraphrase {paraphrase}")
    if fmt not in formats:
        raise KeyError(f"unknown format {fmt}")
    template = conditions[condition][paraphrase]
    format_block = formats[fmt].rstrip("\n")
    # Blind scaffolding only. Model-revised principle text may contain ordinary
    # English words that overlap the eval-awareness list (e.g. "evaluate");
    # aborting the chain would confound the erosion measurement.
    scaffold = template.replace("{CONSTITUTION}", "[CONSTITUTION]").replace(
        "{FORMAT_BLOCK}", format_block
    )
    assert_blinded(scaffold)
    assert_blinded(format_block)
    rendered = template.replace("{CONSTITUTION}", render_constitution(constitution)).replace(
        "{FORMAT_BLOCK}", format_block
    )
    # Subjects must never see category names or item IDs.
    _assert_no_material_leaks(rendered, constitution)
    return rendered


def _assert_no_material_leaks(rendered: str, constitution: Constitution) -> None:
    for cat in CATEGORIES:
        if re.search(rf"\b{cat}\b", rendered):
            raise ValueError(f"rendered prompt leaks category {cat}")
    for meta in constitution.metadata.values():
        if meta.item_id in rendered:
            raise ValueError(f"rendered prompt leaks item_id {meta.item_id}")


def render_forced_prompt(
    constitution: Constitution,
    condition: str,
    paraphrase: Paraphrase,
    extra: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> str:
    extra = extra or {}
    conditions = load_conditions_forced(root)
    formats = load_formats_forced(root)
    if condition not in conditions:
        raise KeyError(f"unknown condition {condition}")
    if paraphrase not in conditions[condition]:
        raise KeyError(f"unknown paraphrase {paraphrase}")
    template = conditions[condition][paraphrase]
    format_block = formats["STRUCTURED"].rstrip("\n")
    target_id = str(extra.get("target_id", "XXX"))
    scaffold = (
        template.replace("{CONSTITUTION}", "[CONSTITUTION]")
        .replace("{FORMAT_BLOCK}", format_block)
        .replace("{TARGET_ID}", target_id)
    )
    assert_blinded(scaffold)
    assert_blinded(format_block)
    rendered = (
        template.replace("{CONSTITUTION}", render_constitution(constitution))
        .replace("{FORMAT_BLOCK}", format_block)
        .replace("{TARGET_ID}", target_id)
    )
    _assert_no_material_leaks(rendered, constitution)
    return rendered


def select_paraphrase_target(
    constitution: Constitution,
    master_seed: int | str,
    config_id: str,
    condition: str,
    chain_idx: int,
    round_idx: int,
) -> str:
    payload = (f"{master_seed}|{config_id}|{condition}|{chain_idx}|{round_idx}|TARGET").encode()
    seed = int(hashlib.sha256(payload).hexdigest()[:16], 16)
    rng = random.Random(seed)
    ids = constitution.ids()
    if not ids:
        raise ValueError("constitution has no principles")
    return rng.choice(ids)


def render_endorsement(constitution: Constitution, *, root: Path | None = None) -> str:
    template = load_endorsement(root)["p1"]
    rendered = template.replace("{CONSTITUTION}", render_constitution(constitution))
    assert_blinded(rendered)
    return rendered


def render_eval_probe(prompt: str, response: str, *, root: Path | None = None) -> str:
    template = load_eval_awareness(root)
    rendered = template.replace("{PROMPT}", prompt).replace("{RESPONSE}", response)
    assert_blinded(rendered, allow_eval_words=True)
    return rendered


def render_realism_clause(clause: str, *, root: Path | None = None) -> str:
    """Render realism-audit prompt. Frozen wording may contain eval vocabulary."""
    template = load_realism_audit(root)
    return template.replace("{CLAUSE}", clause)


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start < 0:
        raise ParseError("no JSON object found")
    # Walk braces to find first top-level object.
    depth = 0
    in_str = False
    escape = False
    end = None
    for i, ch in enumerate(text[start:], start=start):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ParseError("unterminated JSON object")
    candidate = text[start:end]
    trailing = text[end:].strip()
    if trailing:
        raise ParseError("trailing prose after JSON object")
    leading = text[:start].strip()
    if leading:
        raise ParseError("leading prose before JSON object")
    return candidate


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def parse_structured(raw: str, constitution: Constitution) -> RevisionResult:
    try:
        blob = _extract_json_object(raw)
        data = json.loads(blob)
        model = StructuredOutputModel.model_validate(data)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"invalid structured output: {exc}") from exc

    existing = set(constitution.ids())
    seen: list[str] = []
    flags: list[str] = []
    decisions: list[PrincipleDecision] = []

    # D30: normalize bracketed IDs before uniqueness / membership checks.
    normalized_rows: list[Any] = []
    for row in model.principles:
        nid, id_stripped = normalize_opaque_id(row.id)
        mw, mw_stripped = normalize_opaque_id(row.merge_with)
        row_flags: list[str] = []
        if id_stripped or mw_stripped:
            row_flags.append("id_bracket_normalized")
        # Mutate a shallow copy via object.__setattr__ if frozen — pydantic models are mutable.
        row.id = nid  # type: ignore[misc]
        row.merge_with = mw  # type: ignore[misc]
        normalized_rows.append((row, row_flags))

    by_id = {row.id: row for row, _ in normalized_rows}
    if len(by_id) != len(normalized_rows):
        raise ParseError("duplicate ID in principles")

    for row, _ in normalized_rows:
        if row.id not in existing:
            raise ParseError(f"unknown ID {row.id}")
        seen.append(row.id)
    if set(seen) != existing:
        missing = sorted(existing - set(seen))
        raise ParseError(f"missing ID(s): {missing}")

    originals = constitution.text_by_id()
    for row, row_flags in normalized_rows:
        decision = row.decision
        text = row.text
        text, text_stripped = strip_leading_id_prefix(text)
        if text_stripped:
            row_flags.append("text_id_prefix_stripped")
        if decision == "keep":
            if text is None or not str(text).strip():
                raise ParseError(f"{row.id}: keep requires non-empty text")
            if text != originals[row.id]:
                # Exact mismatch (including whitespace-only): treat as revise + flag.
                decision = "revise"
                row_flags.append("keep_text_mismatch")
        elif decision == "revise":
            if text is None or not str(text).strip():
                raise ParseError(f"{row.id}: revise requires non-empty text")
            # ID-prefix-only "revise" is a keep after D30 stripping.
            if text == originals[row.id]:
                decision = "keep"
        elif decision in ("merge", "delete"):
            if text is not None:
                raise ParseError(f"{row.id}: {decision} requires text=null")
            if decision == "merge":
                if not row.merge_with:
                    raise ParseError(f"{row.id}: merge requires merge_with")
                if row.merge_with not in existing:
                    raise ParseError(f"{row.id}: merge_with unknown {row.merge_with}")
                target = by_id[row.merge_with]
                if target.decision not in ("keep", "revise"):
                    raise ParseError(
                        f"{row.id}: merge target {row.merge_with} decision must be keep/revise"
                    )
        if row.note and _word_count(row.note) > 40:
            row_flags.append("note_too_long")
        decisions.append(
            PrincipleDecision(
                id=row.id,
                decision=decision,  # type: ignore[arg-type]
                text=text if decision not in ("merge", "delete") else None,
                merge_with=row.merge_with if decision == "merge" else None,
                note=row.note,
                flags=row_flags,
            )
        )

    # No chains of merges: a merge source must not itself be a merge target of another merge
    # that then merges elsewhere — i.e. merge_with targets must not have decision merge.
    merge_sources = {d.id for d in decisions if d.decision == "merge"}
    for d in decisions:
        if d.decision == "merge" and d.merge_with in merge_sources:
            raise ParseError(f"{d.id}: merge chains are not allowed")

    added: list[AddedPrinciple] = []
    for row in model.added:
        a_flags: list[str] = []
        if not row.text or not row.text.strip():
            raise ParseError("added principle requires non-empty text")
        if row.note and _word_count(row.note) > 40:
            a_flags.append("note_too_long")
        added.append(AddedPrinciple(text=row.text, note=row.note, flags=a_flags))

    return RevisionResult(principles=decisions, added=added, flags=flags)


def apply_revision(constitution: Constitution, result: RevisionResult) -> Constitution:
    next_round = constitution.round + 1
    rng = random.Random(constitution.seed ^ (next_round * 1_000_003))
    used = set(constitution.used_ids)
    originals = constitution.text_by_id()

    new_principles: list[Principle] = []
    new_meta = dict(constitution.metadata)
    lineage = list(constitution.lineage)

    for d in result.principles:
        before = originals[d.id]
        if d.decision in ("keep", "revise"):
            after = d.text if d.text is not None else before
            new_principles.append(Principle(opaque_id=d.id, text=after))
            # If others merged into this ID, record them as co-parents.
            merged_in = [
                x.id for x in result.principles if x.decision == "merge" and x.merge_with == d.id
            ]
            parent_ids = [d.id, *merged_in] if merged_in else [d.id]
            meta = constitution.metadata[d.id]
            lineage.append(
                LineageRecord(
                    round=next_round,
                    opaque_id=d.id,
                    parent_ids=parent_ids,
                    decision=d.decision,
                    merge_with=None,
                    before_text=before,
                    after_text=after,
                    flags=list(d.flags),
                    item_id=meta.item_id,
                    category=meta.category,
                )
            )
        elif d.decision == "merge":
            meta = constitution.metadata[d.id]
            lineage.append(
                LineageRecord(
                    round=next_round,
                    opaque_id=d.id,
                    parent_ids=[d.id],
                    decision="merge",
                    merge_with=d.merge_with,
                    before_text=before,
                    after_text=None,
                    flags=list(d.flags),
                    item_id=meta.item_id,
                    category=meta.category,
                )
            )
        elif d.decision == "delete":
            meta = constitution.metadata[d.id]
            lineage.append(
                LineageRecord(
                    round=next_round,
                    opaque_id=d.id,
                    parent_ids=[d.id],
                    decision="delete",
                    merge_with=None,
                    before_text=before,
                    after_text=None,
                    flags=list(d.flags),
                    item_id=meta.item_id,
                    category=meta.category,
                )
            )

    for k, added in enumerate(result.added):
        oid = _new_opaque_id(rng, used)
        new_principles.append(Principle(opaque_id=oid, text=added.text))
        item_id = f"NEW_{next_round}_{k}"
        new_meta[oid] = HiddenMeta(item_id=item_id, category="EMERGENT", form=None)
        lineage.append(
            LineageRecord(
                round=next_round,
                opaque_id=oid,
                parent_ids=[],
                decision="add",
                merge_with=None,
                before_text=None,
                after_text=added.text,
                flags=list(added.flags),
                item_id=item_id,
                category="EMERGENT",
            )
        )

    return Constitution(
        principles=new_principles,
        metadata=new_meta,
        lineage=lineage,
        config_id=constitution.config_id,
        condition=constitution.condition,
        chain_idx=constitution.chain_idx,
        seed=constitution.seed,
        seed_hex=constitution.seed_hex,
        used_ids=used,
        round=next_round,
    )


def _norm_ws(text: str) -> str:
    return " ".join(text.split())


def parse_forced(raw: str, constitution: Constitution) -> ForcedChange:
    try:
        blob = _extract_json_object(raw)
        data = json.loads(blob)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"invalid forced output: {exc}") from exc
    if "changes" in data or isinstance(data.get("change"), list):
        raise ParseError("two changes")
    try:
        model = ForcedOutputModel.model_validate(data)
    except Exception as exc:
        raise ParseError(f"invalid forced output: {exc}") from exc

    row = model.change
    existing = set(constitution.ids())
    flags: list[str] = []
    nid, id_stripped = normalize_opaque_id(row.id)
    mw, mw_stripped = normalize_opaque_id(row.merge_with)
    if id_stripped or mw_stripped:
        flags.append("id_bracket_normalized")
    row.id = nid  # type: ignore[misc]
    row.merge_with = mw  # type: ignore[misc]
    if row.id not in existing:
        raise ParseError("unknown ID")
    if row.note and _word_count(row.note) > 40:
        flags.append("note_too_long")
    originals = constitution.text_by_id()
    text = row.text
    text, text_stripped = strip_leading_id_prefix(text)
    if text_stripped:
        flags.append("text_id_prefix_stripped")
    if row.action == "revise":
        if text is None or not str(text).strip():
            raise ParseError("revise requires text")
        if _norm_ws(text) == _norm_ws(originals[row.id]):
            raise ParseError("revise text identical")
    elif row.action == "merge":
        if not row.merge_with:
            raise ParseError("missing merge_with")
        if row.merge_with not in existing:
            raise ParseError("unknown ID")
        if row.merge_with == row.id:
            raise ParseError("merge with itself")
        if text is None or not str(text).strip():
            raise ParseError("merge requires text")
    elif row.action == "delete":
        pass
    return ForcedChange(
        id=row.id,
        action=row.action,
        text=text,
        merge_with=row.merge_with,
        note=row.note,
        flags=flags,
    )


def parse_forced_paraphrase(raw: str) -> str:
    try:
        blob = _extract_json_object(raw)
        model = ForcedParaphraseModel.model_validate(json.loads(blob))
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"invalid forced paraphrase: {exc}") from exc
    if not model.text.strip():
        raise ParseError("empty paraphrase text")
    return model.text


def apply_forced(
    constitution: Constitution,
    change: ForcedChange | Literal["paraphrase"],
    *,
    target_id: str | None = None,
    text: str | None = None,
) -> Constitution:
    next_round = constitution.round + 1
    used = set(constitution.used_ids)
    new_principles: list[Principle] = []
    new_meta = dict(constitution.metadata)
    lineage = list(constitution.lineage)

    if change == "paraphrase":
        if not target_id or text is None:
            raise ParseError("paraphrase requires target_id and text")
        if target_id not in set(constitution.ids()):
            raise ParseError("unknown ID")
        for p in constitution.principles:
            after = text if p.opaque_id == target_id else p.text
            new_principles.append(Principle(opaque_id=p.opaque_id, text=after))
            if p.opaque_id == target_id:
                meta = constitution.metadata[p.opaque_id]
                lineage.append(
                    LineageRecord(
                        round=next_round,
                        opaque_id=p.opaque_id,
                        parent_ids=[p.opaque_id],
                        decision="revise",
                        merge_with=None,
                        before_text=p.text,
                        after_text=after,
                        item_id=meta.item_id,
                        category=meta.category,
                    )
                )
        return Constitution(
            principles=new_principles,
            metadata=new_meta,
            lineage=lineage,
            config_id=constitution.config_id,
            condition=constitution.condition,
            chain_idx=constitution.chain_idx,
            seed=constitution.seed,
            seed_hex=constitution.seed_hex,
            used_ids=used,
            round=next_round,
        )

    drop: set[str] = set()
    if change.action == "delete":
        drop.add(change.id)
    if change.action == "merge" and change.merge_with:
        drop.add(change.merge_with)

    for p in constitution.principles:
        meta = constitution.metadata[p.opaque_id]
        if p.opaque_id in drop:
            continue
        if p.opaque_id == change.id and change.action in ("revise", "merge"):
            after = change.text if change.text is not None else p.text
            new_principles.append(Principle(opaque_id=p.opaque_id, text=after))
            parents = [change.id]
            if change.action == "merge" and change.merge_with:
                parents.append(change.merge_with)
            lineage.append(
                LineageRecord(
                    round=next_round,
                    opaque_id=p.opaque_id,
                    parent_ids=parents,
                    decision=change.action,
                    merge_with=change.merge_with if change.action == "merge" else None,
                    before_text=p.text,
                    after_text=after,
                    flags=list(change.flags),
                    item_id=meta.item_id,
                    category=meta.category,
                )
            )
        else:
            new_principles.append(p)

    if change.action == "delete":
        meta = constitution.metadata[change.id]
        before = constitution.text_by_id()[change.id]
        lineage.append(
            LineageRecord(
                round=next_round,
                opaque_id=change.id,
                parent_ids=[change.id],
                decision="delete",
                merge_with=None,
                before_text=before,
                after_text=None,
                flags=list(change.flags),
                item_id=meta.item_id,
                category=meta.category,
            )
        )
    if change.action == "merge" and change.merge_with:
        meta = constitution.metadata[change.merge_with]
        before = constitution.text_by_id()[change.merge_with]
        lineage.append(
            LineageRecord(
                round=next_round,
                opaque_id=change.merge_with,
                parent_ids=[change.merge_with],
                decision="merge",
                merge_with=change.id,
                before_text=before,
                after_text=None,
                flags=list(change.flags),
                item_id=meta.item_id,
                category=meta.category,
            )
        )

    return Constitution(
        principles=new_principles,
        metadata=new_meta,
        lineage=lineage,
        config_id=constitution.config_id,
        condition=constitution.condition,
        chain_idx=constitution.chain_idx,
        seed=constitution.seed,
        seed_hex=constitution.seed_hex,
        used_ids=used,
        round=next_round,
    )


def parse_free(raw: str) -> list[str]:
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^\d+[\.\)\:]\s*", "", stripped)
        stripped = re.sub(r"^[-*]\s*", "", stripped)
        if stripped:
            lines.append(stripped)
    if not lines:
        raise ParseError("empty free-form principle list")
    return lines


def parse_endorsement(raw: str, ids: list[str]) -> tuple[dict[str, int], list[str]]:
    try:
        blob = _extract_json_object(raw)
        model = EndorsementOutput.model_validate(json.loads(blob))
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"invalid endorsement output: {exc}") from exc
    flags: list[str] = []
    got: list[str] = []
    ratings: dict[str, int] = {}
    for r in model.ratings:
        nid, stripped = normalize_opaque_id(r.id)
        if stripped:
            flags.append("id_bracket_normalized")
        assert nid is not None
        got.append(nid)
        ratings[nid] = r.rating
    if len(got) != len(set(got)):
        raise ParseError("duplicate ID in ratings")
    if set(got) != set(ids):
        raise ParseError(f"rating IDs mismatch; missing={sorted(set(ids) - set(got))}")
    return ratings, flags


def parse_eval_probe(raw: str) -> EvalProbeOutput:
    try:
        blob = _extract_json_object(raw)
        return EvalProbeOutput.model_validate(json.loads(blob))
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"invalid eval probe output: {exc}") from exc


def parse_realism(raw: str) -> RealismOutput:
    try:
        blob = _extract_json_object(raw)
        return RealismOutput.model_validate(json.loads(blob))
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"invalid realism output: {exc}") from exc


def trace_lineage(constitution: Constitution, round0_opaque_id: str) -> list[LineageRecord]:
    """Return lineage records whose ancestry includes the given round-0 ID."""
    # Build forward map: parent -> children opaque ids appearing later.
    descendants = {round0_opaque_id}
    out: list[LineageRecord] = []
    for rec in sorted(constitution.lineage, key=lambda r: (r.round, r.opaque_id)):
        if rec.round == 0 and rec.opaque_id == round0_opaque_id:
            out.append(rec)
            continue
        parents = set(rec.parent_ids)
        if rec.merge_with:
            parents.add(rec.merge_with)
        if parents & descendants or rec.opaque_id in descendants:
            out.append(rec)
            if rec.decision in ("keep", "revise", "add") and rec.after_text is not None:
                descendants.add(rec.opaque_id)
            if rec.decision == "merge" and rec.merge_with:
                descendants.add(rec.merge_with)
    return out
