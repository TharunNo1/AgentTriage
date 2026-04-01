import json

from fastapi.responses import StreamingResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agents.triage_agent.agent import root_agent


class SREAgentService:
    def __init__(self):
        self.runner = InMemoryRunner(agent=root_agent, app_name="sre_triage_root_agent")
        self.sessions = {}

    async def analyze_and_report(
        self,
        error: str,
        trace_id: str,
        service_name: str,
        session_id: str | None = None,
    ):
        user_id = "poc"
        if not session_id:
            session = await self.runner.session_service.create_session(user_id=user_id, app_name="sre_triage_root_agent")
        else:
            session = await self.runner.session_service.get_session(
                session_id=session_id, user_id=user_id, app_name="sre_triage_root_agent"
            )

        self.sessions[session_id] = session

        session_input_message = f"""
        [INCOMING SIGNAL DETECTED]
        -------------------------
        Service Name : {service_name}
        Trace ID     : {trace_id}
        Error Signal : {error}
        """
        user_message = types.Content(parts=[types.Part(text=session_input_message)])

        events = self.runner.run_async(session_id=session.id, user_id=user_id, new_message=user_message)

        final_response = ""
        async for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final_response += part.text
        return final_response

    async def analyze_and_report_ui(
        self,
        error: str,
        trace_id: str,
        service_name: str,
        session_id: str | None = None,
    ):
        async def event_generator():
            user_id = "poc"

            if not session_id:
                session = await self.runner.session_service.create_session(user_id=user_id, app_name="sre_triage_root_agent")
            else:
                session = await self.runner.session_service.get_session(
                    session_id=session_id,
                    user_id=user_id,
                    app_name="sre_triage_root_agent",
                )
            session_input_message = f"""
            [INCOMING SIGNAL DETECTED]
            -------------------------
            Service Name : {service_name}
            Trace ID     : {trace_id}
            Error Signal : {error}
            """
            user_message = types.Content(parts=[types.Part(text=session_input_message)])

            events = self.runner.run_async(session_id=session.id, user_id=user_id, new_message=user_message)
            async for event in events:
                # print("EVENT", str(event))
                # 1. Handle Tool Calls (The Agent decides to use a tool)
                if hasattr(event, "content") and event.content.parts:
                    for part in event.content.parts:
                        if part.function_call:
                            # Normalize function call data
                            payload = {
                                "type": "tool",
                                "name": part.function_call.name,
                                "args": part.function_call.args,
                            }
                            yield f"data: {json.dumps(payload)}\n\n"

                        elif part.text:
                            # Normalize text response
                            payload = {"type": "text", "content": part.text}
                            yield f"data: {json.dumps(payload)}\n\n"

                # 2. Handle Tool Outputs (The result returned from your Python functions)
                # Check for 'tool_outputs' or similar attribute in your specific ADK version
                elif hasattr(event, "tool_outputs"):
                    for output in event.tool_outputs:
                        payload = {
                            "type": "output",
                            "tool_name": output.name,
                            "result": str(output.output),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
