# One-shot breakages on SWE-bench

12 one_shot_llm runs changed hidden behavior (9 distinct diffs; the Tier 1 patches are also in Tier 2 and got the same diff).

| run | edit class | cause | files deleted (used) | F2P/P2P failed | PatchDiff changed |
|---|---|---|---|---|---|
| swebench_t1 sympy__sympy-11618__CodeStory | edited source code | rewritten file does not parse (stray quote at the end) | 2 (0) | 5 | 38 |
| swebench_t1 sympy__sympy-11618__LearnByInteract | edited source code | rewritten file does not parse (stray quote at the end) | 1 (0) | 5 | 25 |
| swebench_t1 sympy__sympy-11618__OpenHands | edited source code | rewritten file does not parse (stray quote at the end) | 0 (0) | 5 | 6 |
| swebench_t2 sympy__sympy-11618__CodeStory | edited source code | rewritten file does not parse (stray quote at the end) | 2 (0) | 5 | 38 |
| swebench_t2 sympy__sympy-11618__LearnByInteract | edited source code | rewritten file does not parse (stray quote at the end) | 1 (0) | 5 | 25 |
| swebench_t2 sympy__sympy-11618__OpenHands | edited source code | rewritten file does not parse (stray quote at the end) | 0 (0) | 5 | 6 |
| swebench_t2 scikit-learn__scikit-learn-10844__LearnByInteract | edited source code | rewritten file does not parse (stray quote at the end) | 0 (0) | 17 | 37 |
| swebench_t2 sphinx-doc__sphinx-7454__CodeStory | edited source code | rewritten file does not parse (stray quote at the end) | 1 (0) | 28 | 62 |
| swebench_t2 sphinx-doc__sphinx-7454__LearnByInteract | edited source code | rewritten file does not parse (stray quote at the end) | 0 (0) | 28 | 58 |
| swebench_t2 sphinx-doc__sphinx-7454__OpenHands | edited source code | rewritten file does not parse (stray quote at the end) | 0 (0) | 28 | 0 |
| swebench_t2 django__django-11133__LearnByInteract | edited source code | removed an import still in use (undefined: sys) | 1 (0) | 2 | 0 |
| swebench_t2 django__django-11133__OpenHands | edited source code | removed an import still in use (undefined: sys) | 0 (0) | 2 | 0 |

## Edit types over all patches

| target set | method | patches | with source edits | files deleted | lines in deleted files | source files edited | source lines changed | other files edited |
|---|---|---|---|---|---|---|---|---|
| swebench_t1 | one_shot_llm | 10 | 7 | 10 | 301 | 7 | 20 | 0 |
| swebench_t1 | cleansweep-gatekeeper | 10 | 0 | 20 | 570 | 0 | 0 | 0 |
| swebench_t2 | one_shot_llm | 57 | 37 | 58 | 1666 | 37 | 224 | 0 |
| swebench_t2 | cleansweep-gatekeeper | 57 | 0 | 78 | 2130 | 0 | 0 | 0 |

## Examples

**Removed an import the file still uses (sys)** (`django__django-11133__OpenHands`)

```diff
--- a/django/http/response.py
+++ b/django/http/response.py
@@ -3,7 +3,6 @@ import json
 import mimetypes
 import os
 import re
-import sys
 import time
 from email.header import Header
 from http.client import responses
@@ -557,4 +556,4 @@ class JsonResponse(HttpResponse):
             json_dumps_params = {}
         kwargs.setdefault('content_type', 'application/json')
         data = json.dumps(data, cls=encoder, **json_dumps_params)
```

**A stray quote after the last line: the file no longer parses** (`sympy__sympy-11618__LearnByInteract`)

```diff
--- a/sympy/geometry/point.py
+++ b/sympy/geometry/point.py
         x, y, z = self.args
         m = Transpose(matrix)
-        return Point3D(*(Matrix(1, 4, [x, y, z, 1])*m).tolist()[0][:3])
-
+        return Point3D(*(Matrix(1, 4, [x, y, z, 1])*m).tolist()[0][:3])"
\ No newline at end of file
```

**Removed a helper and inlined its calls (this file also ends with the stray quote)** (`scikit-learn__scikit-learn-10844__LearnByInteract`)

```diff
--- a/sklearn/metrics/cluster/supervised.py
+++ b/sklearn/metrics/cluster/supervised.py
@@ -25,12 +25,6 @@ from ...utils.validation import check_array
 from ...utils.fixes import comb
 
 
-def comb2(n):
-    # the exact version is faster for k == 2: use it by default globally in
-    # this module instead of the float approximate variant
-    return comb(n, 2, exact=1)
-
-
 def check_clusterings(labels_true, labels_pred):
     """Check that the two clusterings matching 1D integer arrays."""
```
