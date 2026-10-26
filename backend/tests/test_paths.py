import pytest

from ofy.download.paths import (
    DEFAULT_TEMPLATE,
    TemplateError,
    artist_key,
    library_artist_name,
    plain_marks,
    render_template,
    sanitize_component,
    validate_template,
)

VALUES = {
    "albumartist": "Radiohead", "artist": "Radiohead", "album": "OK Computer", "title": "Airbag",
    "year": "1997", "disc": 1, "disctotal": 1, "track": 1, "tracktotal": 12, "ext": "mp3",
}


def test_default_template():
    assert str(render_template(DEFAULT_TEMPLATE, VALUES)) == "Radiohead/OK Computer/Radiohead - Airbag.mp3"


def test_multi_disc():
    p = render_template("{albumartist}/{album}/{disc}-{track:02} - {title}.{ext}",
                        {**VALUES, "disc": 2, "disctotal": 2, "track": 7})
    assert p.name == "2-07 - Airbag.mp3"


def test_values_cannot_create_directories():
    p = render_template(DEFAULT_TEMPLATE, {**VALUES, "albumartist": "AC/DC", "title": "../../etc/passwd"})
    assert p.parts[0] == "AC_DC"
    assert ".." not in p.parts
    assert len(p.parts) == 3


@pytest.mark.parametrize("raw,expected", [
    ('What?: "Yes" <No> | * \\', "What__ _Yes_ _No_ _ _ _"),
    ("Trailing dots...", "Trailing dots"),
    ("  spaces  ", "spaces"),
    (".hidden", "hidden"),
    ("CON", "CON_"),
    ("nul.txt", "nul.txt_"),
    ("", "_"),
    ("tab\there", "tab_here"),
])
def test_sanitize_component(raw, expected):
    assert sanitize_component(raw) == expected


def test_max_length_preserves_extension():
    name = "x" * 400 + ".mp3"
    out = sanitize_component(name)
    assert len(out.encode()) <= 180
    assert out.endswith(".mp3")


def test_max_length_multibyte():
    out = sanitize_component("é" * 300)
    assert len(out.encode()) <= 180
    out.encode("utf-8")  # still valid


def test_unicode_kept():
    assert sanitize_component("Sigur Rós – Ágætis byrjun") == "Sigur Rós – Ágætis byrjun"


def test_validate_template():
    validate_template(DEFAULT_TEMPLATE)
    with pytest.raises(TemplateError):
        validate_template("{albumartist}/{nope}.{ext}")
    with pytest.raises(TemplateError):
        validate_template("{albumartist}/{title}")
    with pytest.raises(TemplateError):
        validate_template("/abs/{title}.{ext}")


def test_numeric_format_on_string_value():
    p = render_template("{track:02} {title}.{ext}", {**VALUES, "track": "3"})
    assert str(p) == "03 Airbag.mp3"


def test_album_folder_has_no_year():
    p = render_template(DEFAULT_TEMPLATE, {**VALUES, "albumartist": "Pink Floyd", "artist": "Pink Floyd",
                                           "album": "Meddle", "title": "Echoes", "year": "1971"})
    assert str(p) == "Pink Floyd/Meddle/Pink Floyd - Echoes.mp3"


def test_track_artist_credit_in_file_name():
    p = render_template(DEFAULT_TEMPLATE, {**VALUES, "albumartist": "Daft Punk", "album": "Discovery",
                                           "artist": "Daft Punk feat. Romanthony", "title": "One More Time"})
    assert p.name == "Daft Punk feat. Romanthony - One More Time.mp3"


def test_old_default_template_is_upgraded():
    from ofy.config import Settings
    from ofy.download.paths import LEGACY_DEFAULT_TEMPLATES

    for old in LEGACY_DEFAULT_TEMPLATES:
        assert Settings(path_template=old).path_template == DEFAULT_TEMPLATE
    custom = "{artist}/{year} {album}/{title}.{ext}"
    assert Settings(path_template=custom).path_template == custom


def test_plain_marks():
    assert plain_marks("The B‐52’s") == "The B-52's"


def test_artist_key_ignores_spelling_differences():
    assert artist_key("The Black Eyed Peas") == artist_key("Black Eyed Peas")
    assert artist_key("blink‐182") == artist_key("Blink-182")
    assert artist_key("R.E.M.") == artist_key("R E M")
    assert artist_key("Simon and Garfunkel") == artist_key("Simon & Garfunkel")
    assert artist_key("Neil Young with Crazy Horse") == artist_key("Neil Young & Crazy Horse")
    assert artist_key("Paco de Lucía, Al Di Meola, John McLaughlin") == artist_key(
        "Paco de Lucia, Al Di Meola & John McLaughlin")
    assert artist_key("Chic") != artist_key("The Chicks")


def test_library_artist_name_keeps_the_existing_folder():
    folders = ["The Black Eyed Peas", "blink-182", "R.E.M", "Chic"]
    assert library_artist_name("Black Eyed Peas", folders) == "The Black Eyed Peas"
    assert library_artist_name("blink‐182", folders) == "blink-182"
    assert library_artist_name("R.E.M.", folders) == "R.E.M."  # the folder only lost the final dot
    assert library_artist_name("The Chicks", folders) == "The Chicks"
    assert library_artist_name("Eagle‐Eye Cherry", folders) == "Eagle-Eye Cherry"  # new: plain marks


def test_library_artist_name_finds_a_folder_named_after_the_turned_sort_name():
    assert library_artist_name("土屋アンナ", ["Anna Tsuchiya"], "Tsuchiya, Anna") == "Anna Tsuchiya"
    assert library_artist_name("土屋アンナ", [], "Tsuchiya, Anna") == "土屋アンナ"  # no folder yet: as credited
