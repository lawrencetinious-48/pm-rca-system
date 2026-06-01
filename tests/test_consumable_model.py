from model import Consumable


def test_consumable_has_review_fields():
    # Ensure model exposes the new approval/treatment attributes
    assert hasattr(Consumable, 'is_approved')
    assert hasattr(Consumable, 'approved_by')
    assert hasattr(Consumable, 'approved_at')
    assert hasattr(Consumable, 'treatment_given')
    assert hasattr(Consumable, 'review_notes')
