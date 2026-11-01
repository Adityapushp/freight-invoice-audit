import copy
import pytest
from freight_audit.generator import generate

@pytest.fixture(scope="session")
def starter():
    return generate(seed=20261022, carriers=10, shipments=500, invoices=375)

@pytest.fixture()
def fresh(starter):
    t, gt = starter
    return copy.deepcopy(t), copy.deepcopy(gt)
