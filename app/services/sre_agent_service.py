
from google.genai import types
from google.adk.runners import InMemoryRunner

from app.agents.triage_agent.agent import root_agent


class SREAgentService:

    def __init__(self):
        self.runner = InMemoryRunner(agent=root_agent, app_name='sre_triage_root_agent')
        self.sessions = {}

    async def analyze_and_report(self, error: str, trace_id: str, service_name: str, session_id: str = None):
        user_id = "poc"
        if not session_id:
            session = await self.runner.session_service.create_session(user_id=user_id, app_name='sre_triage_root_agent')
        else:
            session = await self.runner.session_service.get_session(session_id=session_id, user_id=user_id, app_name='sre_triage_root_agent')

        self.sessions[session_id] = session

        session_input_message = f"""
        [INCOMING SIGNAL DETECTED]
        -------------------------
        Service Name : {service_name}
        Trace ID     : {trace_id}
        Error Signal : {error}
        """
        user_message = types.Content(
            parts=[types.Part(text=session_input_message)])

        events = self.runner.run_async(
            session_id=session.id,
            user_id=user_id,
            new_message=user_message
        )

        final_response = ""
        async for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final_response += part.text
        print(final_response)

        return final_response