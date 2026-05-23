from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm


root_agent = Agent(
    name="content_planner_agent",
    model=LiteLlm(model="ollama/llama3.2"),
    description=("Planning agent that creates a detailed and logical outline for a piece of content,"
                 "given a high-level description."),
    instruction=("You are an expert content planner. Your task is to create a detailed and logical outline for a piece"
                 "of content, given a high-level description."),
)