from app.services.offline_ocr_service import extract_text


if __name__ == "__main__":
    image_path = "test.jpg"

    text = extract_text(
        image_path=image_path,
        language="eng",
    )

    print(text)
