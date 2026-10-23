"""UI translations for the recruiter dashboard (English default, Spanish optional).

Keys are the English strings themselves, so templates stay readable and English
needs no dictionary. Missing Spanish entries fall back to English.
"""

from fastapi import Request

LANGUAGES = ("en", "es")
DEFAULT_LANGUAGE = "en"
COOKIE_NAME = "ui_lang"

ES = {
    # navigation
    "Grupo Sazón · Hiring": "Grupo Sazón · Contratación",
    "Candidates": "Candidatos",
    "New applicant (demo)": "Nuevo candidato (demo)",
    # landing
    "Delivery driver screening": "Selección de repartidores",
    "Sofía screens every applicant over chat, any time of day, and recruiters only spend time on qualified candidates.":
        "Sofía entrevista a cada candidato por chat, a cualquier hora, y los reclutadores solo dedican tiempo a los candidatos aptos.",
    "Simulate a new applicant": "Simular un nuevo candidato",
    "Pretend someone just applied to the job ad. Sofía sends the first message and runs the screening, in Spanish or English.":
        "Imagina que alguien acaba de postularse a la oferta. Sofía envía el primer mensaje y hace la preselección, en español o inglés.",
    "Start a conversation →": "Iniciar conversación →",
    "Recruiter dashboard": "Panel de reclutamiento",
    "Every candidate with status, extracted data, AI summary and full transcript. Filter, review and update their status.":
        "Todos los candidatos con su estado, datos extraídos, resumen IA y conversación completa. Filtra, revisa y actualiza su estado.",
    "Open dashboard →": "Abrir panel →",
    # dashboard list
    "applicants screened by Sofía. Qualified candidates are listed first.":
        "candidatos preseleccionados por Sofía. Los aptos aparecen primero.",
    "+ Simulate applicant": "+ Simular candidato",
    "All": "Todos",
    "Search name…": "Buscar nombre…",
    "All countries": "Todos los países",
    "Spain": "España",
    "Mexico": "México",
    "All cities": "Todas las ciudades",
    "Any availability": "Cualquier disponibilidad",
    "Any schedule": "Cualquier horario",
    "Any pipeline stage": "Cualquier etapa",
    "Filter": "Filtrar",
    "Clear": "Limpiar",
    "Candidate": "Candidato",
    "Screening": "Preselección",
    "City": "Ciudad",
    "Availability": "Disponibilidad",
    "Schedule": "Horario",
    "Experience": "Experiencia",
    "Start": "Inicio",
    "Interview": "Entrevista",
    "Pipeline": "Proceso",
    "Updated": "Actualizado",
    "Unnamed applicant": "Candidato sin nombre",
    "stage": "etapa",
    "To schedule": "Por agendar",
    "No candidates match these filters.": "Ningún candidato coincide con estos filtros.",
    "y": "a",
    # statuses and values
    "In progress": "En curso",
    "Qualified": "Apto",
    "Disqualified": "Descartado",
    "Withdrawn": "Retirado",
    "Needs review": "Requiere revisión",
    "Inactive": "Inactivo",
    "New": "Nuevo",
    "Contacted": "Contactado",
    "Interviewed": "Entrevistado",
    "Hired": "Contratado",
    "Rejected": "Rechazado",
    "Full-time": "Jornada completa",
    "Part-time": "Media jornada",
    "Weekends": "Fines de semana",
    "Morning": "Mañana",
    "Afternoon": "Tarde",
    "Evening": "Noche",
    "Flexible": "Flexible",
    "Car": "Coche",
    "Motorbike": "Moto",
    "Car + motorbike": "Coche + moto",
    "Bicycle": "Bicicleta",
    "Other": "Otro",
    "Yes": "Sí",
    "No": "No",
    # candidate detail
    "← All candidates": "← Todos los candidatos",
    "Saved.": "Guardado.",
    "Applied": "Se postuló",
    "Language": "Idioma",
    "AI summary": "Resumen IA",
    "Highlights": "Puntos fuertes",
    "To check": "A verificar",
    "Nothing flagged": "Nada destacado",
    "Next step:": "Siguiente paso:",
    "Summary is being generated, refresh in a few seconds.": "Generando el resumen, actualiza en unos segundos.",
    "Generated automatically when the screening ends. You can also generate one now.":
        "Se genera automáticamente al terminar la preselección. También puedes generarlo ahora.",
    "Screening data": "Datos de la preselección",
    "Full name": "Nombre completo",
    "Driving license": "Carnet / licencia de conducir",
    "Vehicle": "Vehículo",
    "Zone": "Zona",
    "Preferred schedule": "Horario preferido",
    "years": "años",
    "Platforms": "Plataformas",
    "Start date": "Fecha de inicio",
    "(candidate's local time)": "(hora local del candidato)",
    "Disqualified because": "Motivo de descarte",
    "Flags": "Alertas",
    "Conversation": "Conversación",
    "Recruiter actions": "Acciones del reclutador",
    "Pipeline stage": "Etapa del proceso",
    "Notes": "Notas",
    "e.g. Called on Tuesday, very motivated…": "p. ej. Llamado el martes, muy motivado…",
    "Save": "Guardar",
    "More": "Más",
    "Generate AI summary": "Generar resumen IA",
    "Regenerate AI summary": "Regenerar resumen IA",
    "Export JSON": "Exportar JSON",
    "Open candidate chat": "Abrir chat del candidato",
    "Delete candidate data": "Eliminar datos del candidato",
    "Permanently delete this candidate and their conversation?":
        "¿Eliminar definitivamente a este candidato y su conversación?",
}

ES.update({
    "Translate conversation to Spanish": "Traducir conversación al español",
    "Show translation": "Mostrar traducción",
    "Hide translation": "Ocultar traducción",
    "Machine translation shown under each message. The original messages are the source of truth.":
        "Traducción automática bajo cada mensaje. Los mensajes originales son la fuente de verdad.",
    "Translation unavailable right now, please try again.": "Traducción no disponible ahora mismo, inténtalo de nuevo.",
    "Add a note": "Añadir una nota",
    "Activity": "Actividad",
    "No recruiter activity yet.": "Aún no hay actividad del reclutador.",
    "Saved to the activity history below.": "Guardado en el historial de actividad.",
    "Nothing to save: change the pipeline stage or write a note.":
        "Nada que guardar: cambia la etapa del proceso o escribe una nota.",
})

TRANSLATIONS = {"en": {}, "es": ES}

# Names of screening stages / data fields, used inside notes and the dashboard.
CODE_NAMES = {
    "en": {
        "full_name": "name", "license": "driving license", "license_status": "driving license",
        "vehicle": "vehicle", "vehicle_type": "vehicle", "location": "city", "zone": "neighbourhood",
        "availability": "availability", "schedule": "schedule", "preferred_schedule": "schedule",
        "experience": "experience", "experience_years": "experience", "experience_platforms": "platforms",
        "start_date": "start date", "scheduling": "interview scheduling", "done": "finished",
    },
    "es": {
        "full_name": "nombre", "license": "carnet de conducir", "license_status": "carnet de conducir",
        "vehicle": "vehículo", "vehicle_type": "vehículo", "location": "ciudad", "zone": "barrio",
        "availability": "disponibilidad", "schedule": "horario", "preferred_schedule": "horario",
        "experience": "experiencia", "experience_years": "experiencia", "experience_platforms": "plataformas",
        "start_date": "fecha de inicio", "scheduling": "agendando entrevista", "done": "finalizado",
    },
}

# System notes (flags, disqualification reasons) in both languages.
NOTES = {
    "late_start": {"en": "Late start date: {date}", "es": "Fecha de inicio lejana: {date}"},
    "outside_area": {"en": "Lives in {place} (outside service area)", "es": "Vive en {place} (fuera de la zona de servicio)"},
    "out_of_area": {"en": "Outside service area ({place})", "es": "Fuera de la zona de servicio ({place})"},
    "no_license": {"en": "No driving license", "es": "Sin carnet de conducir"},
    "license_pending": {"en": "Driving license not obtained yet", "es": "Aún no tiene el carnet de conducir"},
    "unclear_review": {"en": "No clear answer about {stage} after {tries} tries",
                       "es": "Sin respuesta clara sobre {stage} tras {tries} intentos"},
    "unclear_skipped": {"en": "No clear answer about {stage} (question skipped)",
                        "es": "Sin respuesta clara sobre {stage} (pregunta omitida)"},
    "deletion_requested": {"en": "Candidate requested deletion of their data",
                           "es": "El candidato pidió que se borren sus datos"},
    "abusive": {"en": "Repeated inappropriate messages", "es": "Mensajes inapropiados repetidos"},
    "schedule_manually": {"en": "Interview time to be arranged by a recruiter",
                          "es": "Un reclutador debe acordar la hora de la entrevista"},
    "changed_after_close": {"en": "After the screening ended, the candidate tried to change: {fields}",
                            "es": "Tras terminar la preselección, el candidato intentó cambiar: {fields}"},
    "license_corrected": {"en": "Said they had no driving license, then corrected it to Yes after being disqualified",
                          "es": "Dijo que no tenía carnet y, tras ser descartado, lo corrigió a Sí"},
    "location_corrected": {"en": "First said they live in {old}, then corrected it to {new} after being disqualified",
                           "es": "Primero dijo que vive en {old} y, tras ser descartado, lo corrigió a {new}"},
    "repeated_knockout_change": {"en": "Changed their {stage} answer again after a correction: needs human review",
                                 "es": "Volvió a cambiar su respuesta sobre {stage} tras una corrección: requiere revisión"},
    "text": {"en": "{text}", "es": "{text}"},
}


def conversation_languages(messages) -> set[str]:
    """Languages the candidate wrote in, as detected by the extraction step on each message.

    The agent always mirrors the candidate's language; its opening message is a fixed
    bilingual template, so it doesn't count.
    """
    return {m.meta["extraction"]["language"] for m in messages
            if m.role == "candidate" and m.meta.get("extraction", {}).get("language")}


def code_name(code: str, lang: str) -> str:
    return CODE_NAMES.get(lang, CODE_NAMES["en"]).get(code, code)


def render_note(note, lang: str) -> str:
    template = NOTES.get(note.code, NOTES["text"])
    params = dict(note.params)
    if "stage" in params:
        params["stage"] = code_name(params["stage"], lang)
    if "fields" in params:
        params["fields"] = ", ".join(code_name(f.strip(), lang) for f in params["fields"].split(","))
    try:
        return template.get(lang, template["en"]).format(**params)
    except KeyError:
        return note.code


def get_language(request: Request) -> str:
    lang = request.cookies.get(COOKIE_NAME, DEFAULT_LANGUAGE)
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def translate(text: str, lang: str) -> str:
    return TRANSLATIONS.get(lang, {}).get(text, text)


def i18n_context(request: Request) -> dict:
    """Jinja2 context processor: every template gets the current UI language."""
    return {"lang": get_language(request)}
