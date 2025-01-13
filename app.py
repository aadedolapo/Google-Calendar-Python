import streamlit as st
import psycopg2 as psy
from psycopg2.extras import RealDictCursor
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle
from datetime import datetime, timedelta
import json
import streamlit.components.v1 as components

# Load PostgreSQL credentials
with open('pg_credentials.txt', 'r') as f:
    file = f.read()
exec(file)

SCOPES = ['https://www.googleapis.com/auth/calendar']

# Database connection function


@st.cache_resource
def get_db_connection():
    try:
        conn = psy.connect(
            host=hostname,
            dbname=database,
            user=username,
            password=pwd,
            port=port_id
        )
        return conn
    except Exception as e:
        st.error(f"Error connecting to the database: {e}")
        return None

# Google Calendar Authentication


def authenticate_google():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'api_credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

# Fetch events from Google Calendar


def fetch_google_events(service):
    events_result = service.events().list(
        calendarId='primary',
        timeMin=datetime.utcnow().isoformat() + 'Z',
        maxResults=10,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    return events_result.get('items', [])

# Fetch events from PostgreSQL


def fetch_postgres_events():
    conn = get_db_connection()
    events = []
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM events ORDER BY start_time ASC")
                events = cursor.fetchall()
        except Exception as e:
            st.error(f"Error fetching events from the database: {e}")
    return events

# Insert event into PostgreSQL with calendar_id and event_id


def insert_postgres_event(calendar_id, title, description, start_time, end_time):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                script2 = """DROP TABLE IF EXISTS events"""
                cursor.execute(script2)
                # Create events table if it doesn't exist
                script = """CREATE TABLE IF NOT EXISTS events (
                                id SERIAL PRIMARY KEY,
                                calendar_id TEXT NOT NULL,
                                title TEXT NOT NULL,
                                description TEXT,
                                start_time TIMESTAMP WITH TIME ZONE NOT NULL,
                                end_time TIMESTAMP WITH TIME ZONE NOT NULL
                            );
                            """
                cursor.execute(script)
                conn.commit()  # Commit after creating the table

                # Insert the event into the database
                cursor.execute(
                    """
                    INSERT INTO events (calendar_id, title, description, start_time, end_time)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (calendar_id, title, description,
                     start_time, end_time)  # 5 parameters
                )
                conn.commit()  # Commit after inserting the event
                st.info("Event saved to the database.")

        except Exception as e:
            conn.rollback()
            st.error(f"Error inserting event into PostgreSQL: {e}")


def insert_event(service, calendar_id, title, description, start_time, end_time):
    event = {
        'summary': title,
        'description': description,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'UTC'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'UTC'},
    }
    created_event = service.events().insert(
        calendarId=calendar_id, body=event).execute()

    insert_postgres_event(calendar_id, title,
                          description, start_time, end_time)
    return created_event

# Delete event from Google Calendar


def delete_google_event(service, calendar_id, event_id):
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        st.success("Event deleted from Google Calendar.")
    except Exception as e:
        st.error(f"Error deleting event from Google Calendar: {e}")

# Delete event from PostgreSQL


def delete_postgres_event(event_id):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
                conn.commit()
                st.success("Event deleted from PostgreSQL.")
        except Exception as e:
            conn.rollback()
            st.error(f"Error deleting event from PostgreSQL: {e}")

# Manage events (Add/Update/Delete)


def manage_events():
    st.title("📅 Manage Events")
    creds = authenticate_google()
    service = build('calendar', 'v3', credentials=creds)

    st.subheader("Add a New Event")
    with st.form("event_form"):
        title = st.text_input("Event Title")
        description = st.text_area("Event Description")
        start_date = st.date_input(
            "Start Date", datetime.utcnow().date() + timedelta(days=1))
        start_time = st.time_input("Start Time", datetime.utcnow().time())
        end_date = st.date_input(
            "End Date", datetime.utcnow().date() + timedelta(days=1))
        end_time = st.time_input(
            "End Time", (datetime.utcnow() + timedelta(hours=1)).time())

        submit_event = st.form_submit_button("Add Event")

        if submit_event:
            if not title:
                st.error("Event title is required!")
            elif datetime.combine(start_date, start_time) >= datetime.combine(end_date, end_time):
                st.error("Start time must be before end time!")
            else:
                created_event = insert_event(
                    service,
                    'primary',
                    title,
                    description,
                    datetime.combine(start_date, start_time),
                    datetime.combine(end_date, end_time)
                )
                st.success(f"Event created: {created_event['htmlLink']}")

    # Delete Events Section
    st.subheader("Delete Events")

    # Search for Events to Delete
    event_title = st.text_input("Enter Event Title to Search and Delete")

    if event_title:
        # Fetch Google Calendar events
        google_events = fetch_google_events(service)
        matched_google_events = [event for event in google_events if event_title.lower(
        ) in event.get('summary', '').lower()]

        if matched_google_events:
            st.write(
                f"Found {len(matched_google_events)} event(s) matching '{event_title}':")
            for event in matched_google_events:
                title = event.get('summary', 'No title')
                event_id = event['id']
                # Provide a unique key using the event ID
                if st.button(f"Delete Google Event: {title}", key=f"google_{event_id}"):
                    delete_google_event(service, 'primary', event_id)

        else:
            st.write("No Google Calendar events found matching the search term.")

        # Fetch PostgreSQL events
        postgres_events = fetch_postgres_events()
        matched_postgres_events = [
            event for event in postgres_events if event_title.lower() in event['title'].lower()]

        if matched_postgres_events:
            st.write(
                f"Found {len(matched_postgres_events)} event(s) matching '{event_title}':")
            for event in matched_postgres_events:
                title = event['title']
                event_id = event['id']
                # Provide a unique key using the event ID
                if st.button(f"Delete Postgres Event: {title}", key=f"postgres_{event_id}"):
                    delete_postgres_event(event_id)
        else:
            st.write("No PostgreSQL events found matching the search term.")

# Display calendar using FullCalendar


def display_calendar():
    st.title("📅 Google Events Calendar")
    creds = authenticate_google()
    service = build('calendar', 'v3', credentials=creds)

    # Fetch events
    google_events = fetch_google_events(service)
    postgres_events = fetch_postgres_events()
    events = []

    for event in google_events:
        start_time = event['start'].get('dateTime', event['start'].get('date'))
        end_time = event['end'].get('dateTime', event['end'].get('date'))
        events.append({
            "title": event.get('summary', 'No title'),
            "start": start_time,
            "end": end_time,
            "description": event.get('description', 'No description')
        })

    for event in postgres_events:
        events.append({
            "title": event['title'],
            "start": event['start_time'].isoformat(),
            "end": event['end_time'].isoformat(),
            "description": event['description']
        })

    calendar_data = json.dumps(events)

    html_string = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link href="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.css" rel="stylesheet" />
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.js"></script>
        <style>
            body {{
                background-color: #2E2E2E; /* Dark background */
                color: #ffffff; /* Light text */
                font-family: Arial, sans-serif;
            }}
            #calendar {{
                max-width: 900px;
                max-height: 900px;
                margin: 40px auto;
            }}
            .fc-toolbar {{
                color: #ffffff; /* Toolbar buttons and title text */
            }}
            .fc-daygrid-day-number {{
                color: #ffffff; /* Date numbers in the grid */
            }}
            .fc-event {{
                border-radius: 5px; /* Rounded event corners */
                box-shadow: 0 2px 5px rgba(0, 0, 0, 0.5); /* Subtle shadow for events */
            }}
        </style>
    </head>
    <body>
        <div id="calendar"></div>
        <script>
            document.addEventListener('DOMContentLoaded', function() {{
                var calendarEl = document.getElementById('calendar');
                var calendar = new FullCalendar.Calendar(calendarEl, {{
                    initialView: 'dayGridMonth',
                    headerToolbar: {{
                        left: 'prev,next today',
                        center: 'title',
                        right: 'dayGridMonth,timeGridWeek,timeGridDay'
                    }},
                    events: {calendar_data},
                    eventClick: function(info) {{
                        alert('Event: ' + info.event.title + '\\n' +
                              'Start: ' + info.event.start + '\\n' +
                              'End: ' + info.event.end + '\\n' +
                              'Description: ' + (info.event.extendedProps.description || 'No description'));
                    }}
                }});
                calendar.render();
            }});
        </script>
    </body>
    </html>
    """

    components.html(html_string, height=800, width=900)

# Main app


def main():
    st.sidebar.title("Google Calendar Menu")
    choice = st.sidebar.selectbox(
        "Choose an option", ["Manage Events", "View Calendar"])

    if choice == "Manage Events":
        manage_events()
    elif choice == "View Calendar":
        display_calendar()


if __name__ == "__main__":
    main()
