from calc.m1 import f1
from calc.m2 import f2
from calc.m3 import f3
from calc.m4 import f4
from calc.m5 import f5
from calc.m6 import f6


def test_all():
    assert f1(0) == 1 and f2(0) == 2 and f3(0) == 3 and f4(0) == 4 and f5(0) == 5 and f6(0) == 6
