# AliExpress Stock Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correctly recognize successful `update-sku-stock` responses without weakening validation for other AliExpress operations.

**Architecture:** Keep `_is_success_response` unchanged for shared product mutations. Add a stock-update-specific predicate that accepts only non-empty `results` lists whose entries all contain `ok is True`, and make `update_stock` use it.

**Tech Stack:** Python, Django `TestCase`, `unittest.mock`

## Global Constraints

- Do not use `group_id`, `task_id`, or `external_id` as success indicators.
- Reject missing or empty `results`, malformed result items, any `ok` value other than the boolean `True`, and top-level `error`, `errors`, or `code` keys.
- Preserve the existing warning and `False` return for rejected responses.
- Do not change `_is_success_response`, deletion, or publication behavior.

---

### Task 1: Validate AliExpress stock-update result responses

**Files:**
- Modify: `aliexpress/tests.py`
- Modify: `src/lekala_class/class_marketplace/AliExpress.py`

**Interfaces:**
- Consumes: `AliExpress.update_stock(params=None, data=None, save_to_file=False) -> bool`
- Produces: `AliExpress._is_stock_update_success_response(response) -> bool`

- [ ] **Step 1: Write regression tests for the observed success response and strict failure cases**

Add tests to `AliExpressReconciliationTests`:

```python
@patch.object(
    AliExpress,
    '_request',
    return_value={
        'group_id': '728551676',
        'results': [
            {'ok': True, 'task_id': '0', 'errors': {}, 'external_id': ''},
            {'ok': True, 'task_id': '0', 'errors': {}, 'external_id': ''},
        ],
    },
)
def test_update_stock_accepts_successful_result_list(self, request):
    output = StringIO()

    with redirect_stdout(output):
        result = AliExpress().update_stock(data=[])

    self.assertTrue(result)
    self.assertNotIn('AliExpress отклонил обновление остатков', output.getvalue())

@patch.object(AliExpress, '_request')
def test_update_stock_rejects_incomplete_result_list(self, request):
    client = AliExpress()
    for response in (
        {'group_id': '1', 'results': []},
        {'group_id': '1', 'results': [{'ok': True}, {'ok': False}]},
        {'group_id': '1', 'results': [{'ok': True}, {}]},
        {'group_id': '1', 'results': [{'ok': True}, 'malformed']},
        {'group_id': '1', 'results': [{'ok': 1}]},
    ):
        with self.subTest(response=response):
            request.return_value = response
            self.assertFalse(client.update_stock(data=[]))

@patch.object(
    AliExpress,
    '_request',
    return_value={
        'error': 'denied',
        'results': [{'ok': True}],
    },
)
def test_update_stock_rejects_top_level_error_with_successful_results(self, request):
    self.assertFalse(AliExpress().update_stock(data=[]))
```

Update the artificial successful response in
`test_update_stock_retries_rate_limit_response` from `{"data": {}}` to the
real endpoint shape:

```python
successful._content = b'{"group_id": "1", "results": [{"ok": true}]}'
```

- [ ] **Step 2: Run the focused tests and verify the observed response fails**

Run:

```powershell
python manage.py test aliexpress.tests.AliExpressReconciliationTests
```

Expected: `test_update_stock_accepts_successful_result_list` and the updated
rate-limit test fail because `_is_success_response` does not recognize
`results[].ok`; existing rejection tests remain green.

- [ ] **Step 3: Implement the endpoint-specific predicate**

In `AliExpress.update_stock`, replace the predicate call with:

```python
if not self._is_stock_update_success_response(response):
```

Add beside `_is_success_response`:

```python
@staticmethod
def _is_stock_update_success_response(response) -> bool:
    if not isinstance(response, dict):
        return False
    if any(key in response for key in ('error', 'errors', 'code')):
        return False
    results = response.get('results')
    return (
        isinstance(results, list)
        and bool(results)
        and all(
            isinstance(result, dict) and result.get('ok') is True
            for result in results
        )
    )
```

- [ ] **Step 4: Run focused and full AliExpress tests**

Run:

```powershell
python manage.py test aliexpress
```

Expected: all AliExpress tests pass.

- [ ] **Step 5: Run repository checks and inspect the final diff**

Run:

```powershell
python manage.py test
git diff --check
git diff -- aliexpress/tests.py src/lekala_class/class_marketplace/AliExpress.py
```

Expected: the full test suite passes, `git diff --check` emits no errors, and
the diff contains only the scoped test and client changes.

- [ ] **Step 6: Commit the implementation**

```powershell
git add -- aliexpress/tests.py src/lekala_class/class_marketplace/AliExpress.py docs/superpowers/plans/2026-07-30-ali-stock-response.md
git commit -m "Исправить обработку ответа остатков AliExpress"
```
