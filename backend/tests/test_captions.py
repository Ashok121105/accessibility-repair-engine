from backend.app.services.captions import (
    CaptionHistory,
    create_caption_entry,
    detect_page_status_announcements,
    detect_video_caption_tracks,
    extract_payment_status,
    is_sensitive_caption_text,
    sanitize_caption_text,
)


def test_caption_history_is_bounded_and_can_be_cleared() -> None:
    history = CaptionHistory(max_entries=2)
    first = create_caption_entry(source="assistant", text="Hello")
    second = create_caption_entry(source="website", text="Welcome")
    third = create_caption_entry(source="payment", text="Payment successful")

    history.add(first)
    history.add(second)
    history.add(third)

    assert len(history.entries) == 2
    assert history.entries[-1].text == "Payment successful"
    history.clear()
    assert history.entries == []


def test_sensitive_caption_values_are_redacted() -> None:
    text = "Payment method selected: UPI. OTP 123456 and CVV 123 will be entered on the website."

    sanitized = sanitize_caption_text(text)

    assert "123456" not in sanitized
    assert "123" not in sanitized
    assert "[REDACTED]" in sanitized
    assert is_sensitive_caption_text(sanitized) is True


def test_detects_video_captions_and_missing_tracks() -> None:
    html = """
    <video>
      <track kind="captions" label="English" srclang="en" src="captions-en.vtt" />
      <track kind="subtitles" label="Hindi" srclang="hi" />
    </video>
    """

    result = detect_video_caption_tracks(html)
    assert result["captions_available"] is True
    assert result["caption_tracks"][0]["language"] == "en"
    assert result["caption_tracks"][0]["kind"] == "captions"

    missing = detect_video_caption_tracks("<div>No captions available</div>")
    assert missing["captions_available"] is False
    assert missing["caption_tracks"] == []


def test_payment_status_and_page_status_announcements_are_detected() -> None:
    announcement_text = "Payment unsuccessful. Payment failed. Cart updated. Order confirmed."

    assert extract_payment_status(announcement_text)["status"] == "failed"
    assert detect_page_status_announcements(announcement_text) == [
        "payment failed",
        "order confirmed",
        "cart updated",
    ]


def test_payment_method_and_order_ids_are_preserved_like_valid_sensitive_values() -> None:
    sanitized = sanitize_caption_text("Order ID: AB12CD34, URL: https://example.com/pay, price ₹499, UPI selected")

    assert "AB12CD34" in sanitized
    assert "https://example.com/pay" in sanitized
    assert "₹499" in sanitized
    assert "UPI" in sanitized
