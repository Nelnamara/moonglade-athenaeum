import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { detailAdvParams, detailStackOf } from "../../gallery/src/lib/detailParams.js";

// #81: the picture page's position ("k of N") and Prev/Next left the View batch drill-down, because the
// params the page sends to /api/detail never carried `batch`. detailAdvParams is the one builder both
// shells use now. The opened stack (?series=<sid>) is the same defect: the list route honours it, the
// params the page sent did not carry it.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");

const ADV = {
  sort: "newest", ratingMin: 0, model: "", lora: "", dateFrom: "", dateTo: "",
  source: "", tag: "", publishedOnly: false, batch: "", series: "",
};

describe("detailAdvParams: the filters the picture page sends to /api/detail", () => {
  test("an open View batch rides along as `batch`, the name the list route and the detail route read", () => {
    const p = detailAdvParams({ applied: "", media: "", shelf: "", adv: { ...ADV, batch: "744376191043610001" } });
    assert.equal(p.batch, "744376191043610001");
  });

  test("an opened stack rides along as `series`, the name the list route and the detail route read", () => {
    const p = detailAdvParams({ applied: "", media: "", shelf: "", adv: { ...ADV, series: "X1" } });
    assert.equal(p.series, "X1");
  });

  test("no stack open sends an empty series, which the hook drops from the query string", () => {
    assert.ok(!detailAdvParams({ applied: "", media: "", shelf: "", adv: ADV }).series);
    assert.ok(!detailAdvParams({ applied: "", media: "", shelf: "", adv: undefined }).series);
  });

  test("no batch open sends an empty value, which the hook drops from the query string", () => {
    const p = detailAdvParams({ applied: "", media: "", shelf: "", adv: ADV });
    assert.ok(!p.batch);
  });

  test("it still carries every other filter under the list route's own names", () => {
    const p = detailAdvParams({
      applied: "elf", media: "image", shelf: "keepers",
      adv: { ...ADV, sort: "oldest", ratingMin: 3, model: "M", lora: "L", dateFrom: "2026-01-01",
        dateTo: "2026-02-01", source: "online", tag: "t", publishedOnly: true, batch: "T1", series: "S1" },
    });
    assert.deepEqual(p, {
      q: "elf", media: "image", collection: "keepers", sort: "oldest", rating_min: 3,
      model: "M", lora: "L", from: "2026-01-01", to: "2026-02-01", source: "online", tag: "t",
      published: "1", batch: "T1", series: "S1",
    });
  });

  test("the default sort is left off the wire, a missing adv does not throw", () => {
    assert.equal(detailAdvParams({ applied: "", media: "", shelf: "", adv: ADV }).sort, "");
    assert.doesNotThrow(() => detailAdvParams({ applied: "", media: "", shelf: "", adv: undefined }));
  });

  test("every key it sends is one the library list sends too (a batch the list honours, the detail honours)", () => {
    const lib = src("gallery/src/hooks/useLibrary.js");
    const pageQuery = lib.slice(lib.indexOf("const pageQuery"), lib.indexOf("const load = useCallback"));
    const listKeys = [...pageQuery.matchAll(/\b(\w+)\s*(?=[:,])/g)].map((m) => m[1]);
    const detail = detailAdvParams({ applied: "", media: "", shelf: "", adv: ADV });
    for (const k of Object.keys(detail)) assert.ok(listKeys.includes(k), "the list route has no `" + k + "`");
  });
});

describe("both shells build the detail params with the shared builder, and re-fetch when the batch changes", () => {
  for (const [name, file, dep, depSeries] of [
    ["desktop App.jsx", "gallery/src/App.jsx", "adv.batch", "adv.series"],
    ["phone AppMobile.jsx", "gallery/src/components/AppMobile.jsx", "lib.adv.batch", "lib.adv.series"],
  ]) {
    test(name, () => {
      const s = src(file);
      assert.match(s, /import \{ detailAdvParams(, detailStackOf)? \} from "\.{1,2}\/(lib\/)?detailParams\.js";/);
      const at = s.indexOf("const detailsAdvParams = useMemo(");
      assert.ok(at > 0, "detailsAdvParams is still memoized");
      const memo = s.slice(at, s.indexOf("]);", at) + 3);
      assert.match(memo, /detailAdvParams\(/);
      assert.ok(memo.includes(dep), "the memo's dependency list names " + dep);
      assert.ok(memo.includes(depSeries), "the memo's dependency list names " + depSeries);
    });
  }
});

// A picture opened from the stack MODAL (desktop only: the phone has no stack modal). The modal leaves
// adv alone so the library behind it does not move, so the stack has to ride with the Details-open
// state instead -- else "k of N" and Prev/Next left the stack (the same defect again). A series stack
// scopes by `series` (its sid), a batch stack by `batch` (its task id), never both.
describe("a picture opened from the stack modal carries that stack", () => {
  const none = { applied: "", media: "", shelf: "" };
  const SERIES = { kind: "series", id: "S9" };
  const BATCH = { kind: "batch", id: "744376191043610001" };

  test("a series stack rides as `series` and no batch; the caller's adv is never written to", () => {
    const adv = { ...ADV };
    const p = detailAdvParams({ ...none, adv, stack: SERIES });
    assert.equal(p.series, "S9");
    assert.ok(!p.batch);
    assert.deepEqual(adv, ADV, "adv (the grid behind the modal) is untouched");
  });

  test("a batch stack rides as `batch` (its task id) and no series; adv is untouched", () => {
    const adv = { ...ADV };
    const p = detailAdvParams({ ...none, adv, stack: BATCH });
    assert.equal(p.batch, "744376191043610001");
    assert.ok(!p.series);
    assert.deepEqual(adv, ADV);
  });

  test("never both: the stack's kind wins over a batch or series left in adv", () => {
    const left = { ...ADV, batch: "OLDB", series: "OLDS" };
    const a = detailAdvParams({ ...none, adv: left, stack: SERIES });
    assert.equal(a.series, "S9");
    assert.ok(!a.batch);
    const b = detailAdvParams({ ...none, adv: left, stack: BATCH });
    assert.equal(b.batch, "744376191043610001");
    assert.ok(!b.series);
  });

  test("opened from the grid (no stack): neither is sent, and a drill-down in adv rides exactly as before", () => {
    for (const stack of [undefined, null, {}, { kind: "series", id: "" }, { kind: "other", id: "x" }]) {
      const p = detailAdvParams({ ...none, adv: ADV, stack });
      assert.ok(!p.series && !p.batch, "no stack, no scope: " + JSON.stringify(stack));
    }
    const p = detailAdvParams({ ...none, adv: { ...ADV, batch: "T1", series: "S1" } });
    assert.equal(p.batch, "T1");
    assert.equal(p.series, "S1");
  });

  test("detailStackOf: a known kind with an id gives { kind, id }; anything else is no stack", () => {
    assert.deepEqual(detailStackOf({ kind: "series", id: "X1" }), { kind: "series", id: "X1" });
    assert.deepEqual(detailStackOf({ kind: "batch", id: 744376191043610001n }), { kind: "batch", id: "744376191043610001" });
    assert.equal(detailStackOf(null), null);
    assert.equal(detailStackOf(undefined), null);
    assert.equal(detailStackOf({ kind: "series", id: "" }), null);
    assert.equal(detailStackOf({ kind: "similar", id: "x" }), null);
  });

  const app = src("gallery/src/App.jsx");
  const body = (head) => {
    const at = app.indexOf(head);
    assert.ok(at > 0, head + " is still there");
    return app.slice(at, app.indexOf("\n  }, [", at));
  };

  test("openDetailsFromStack hands Details the stack, read before the stack closes, and never writes adv", () => {
    const fn = body("const openDetailsFromStack = useCallback(");
    const read = fn.indexOf("detailStackOf(stackFor)");
    assert.ok(read > 0, "the scope is read off stackFor (either kind)");
    assert.ok(read < fn.indexOf("closeStack();"), "...before closeStack() clears the stack");
    assert.match(fn, /setDetailsStack\(scope\)/);
    assert.ok(!/setAdv/.test(fn), "adv is not touched: the grid behind the modal must not re-load");
    assert.match(app, /\}, \[setUrl, closeStack, openDetails, stackFor\]\);/, "stackFor is a dependency");
  });

  test("a record opened from the grid carries no stack: only openDetailsFromStack ever sets one", () => {
    assert.equal(app.match(/setDetailsStack\([^)]*\)/g).filter((c) => c !== "setDetailsStack(null)").join(), "setDetailsStack(scope)");
    assert.match(app, /const \[detailsStack, setDetailsStack\] = useState\(null\);/);
  });

  test("the scope is dropped on every way Details closes, and kept when stepping between pictures", () => {
    assert.match(body("const closeDetails = useCallback("), /setDetailsStack\(null\)/);
    assert.match(body("const goLibrary = useCallback("), /setDetailsStack\(null\)/);
    assert.match(body("const onPop = () => {"), /if \(!popImage\) setDetailsStack\(null\)/);
    // Prev/Next and lineage links call onNavigate -> openDetails; that must NOT clear the scope.
    assert.ok(!/setDetailsStack/.test(body("const openDetails = useCallback(")), "openDetails leaves the scope alone");
  });

  test("the memoized detail params take the stack and re-fetch when it changes", () => {
    const at = app.indexOf("const detailsAdvParams = useMemo(");
    const memo = app.slice(at, app.indexOf("]);", at) + 3);
    assert.match(memo, /stack: detailsStack/);
    assert.match(memo, /,\s*detailsStack\]\);$/, "detailsStack is in the dependency list");
  });
});
