"""The 'which folders belong to this case' view groups evidence source paths
into human-scale folders: drive + two components, parent for shallow paths."""
from app.api.evidence import _source_folder_of


def test_deep_paths_group_at_drive_plus_two():
    assert _source_folder_of(
        r"F:\AMIR-1\Investigations\חומר נוסף 31.05.26\שמע\call.wav"
    ) == r"F:\AMIR-1\Investigations"
    assert _source_folder_of(
        r"D:\Users\hal92\Documents\JEROS\doc.pdf"
    ) == r"D:\Users\hal92"


def test_shallow_paths_fall_back_to_parent():
    assert _source_folder_of(r"F:\AMIR-1\file.txt") == r"F:\AMIR-1"
    assert _source_folder_of(r"F:\file.txt") == "F:\\"


def test_unc_share_paths():
    # the UNC root (\\server\share) plays the role of the drive, so the rule
    # stays "root + two components" — same shape as F:\AMIR-1\Investigations
    assert _source_folder_of(
        r"\\server\share\case\deep\file.txt"
    ) == "\\\\server\\share\\case\\deep"
    assert _source_folder_of(
        r"\\server\share\case\file.txt"
    ) == "\\\\server\\share\\case"
