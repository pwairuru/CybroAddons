def migrate(cr, version):
    cr.execute("""
        UPDATE account_payment ap
        SET hotel_booking_id = hf.booking_id
        FROM hotel_folio hf
        WHERE ap.hotel_folio_id = hf.id
          AND ap.hotel_booking_id IS NULL
          AND hf.booking_id IS NOT NULL
    """)
