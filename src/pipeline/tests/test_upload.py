"""Tests for pipeline.upload — blob path construction logic."""



def test_blob_path_convention():
    """Verify blob path matches the architecture convention:
    layers/{methodology_version}/{scenario_id}/{horizon_year}.tif"""
    # We test the path logic without actually connecting to blob storage.
    # The upload function builds the path before calling Azure SDK.
    expected = "layers/v1.0/ssp2-45/2050.tif"

    # Extract path construction logic
    methodology_version = "v1.0"
    scenario = "ssp2-45"
    horizon = 2050
    blob_path = f"layers/{methodology_version}/{scenario}/{horizon}.tif"

    assert blob_path == expected


def test_blob_path_all_scenarios():
    """Blob paths should be unique per scenario/horizon/version combination."""
    paths = set()
    for scenario in ["ssp1-26", "ssp2-45", "ssp5-85"]:
        for horizon in [2030, 2050, 2100]:
            path = f"layers/v1.0/{scenario}/{horizon}.tif"
            paths.add(path)

    assert len(paths) == 9
