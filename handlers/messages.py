def get_upload_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("upload", upload_start)],
        states={
            UPLOAD_JSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, upload_receive)],
        },
        fallbacks=[CommandHandler("cancel", upload_cancel)],
    )
