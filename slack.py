import os

import openai

from dotenv import load_dotenv
from slack_bolt import App
from classification import classify_question
from inference import get_response


CHAT_HISTORY_LIMIT = "20"

load_dotenv()

## Initialize OpenAI
openai.api_key = os.environ.get("OPENAI_TOKEN")
models = [m.id for m in openai.Model.list()["data"]]
print(f"Available models: {', '.join(models)}")

## "gpt-4" and "gpt-3.5-turbo" are the two we'll use here

# Initializes your app with your bot token and signing secret
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)


# Add functionality here
# @app.event("app_home_opened") etc
@app.event("app_home_opened")
def update_home_tab(client, event, logger):
    try:
        # views.publish is the method that your app uses to push a view to the Home tab
        client.views_publish(
            # the user that opened your app's app home
            user_id=event["user"],
            # the view object that appears in the app home
            view={
                "type": "home",
                "callback_id": "home_view",
                # body of the view
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Welcome to your _App's Home_* :tada:",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "This button won't do much for now but you can set up a listener for it using the `actions()` method and passing its unique `action_id`. See an example in the `examples` folder within your Bolt app.",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Click me!"},
                            }
                        ],
                    },
                ],
            },
        )

    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")


def summarize_thread(thread):
    prompt = f"""The following is a conversation in which the first person asks a question. Eventually, after the second person may ask some clairfying questions to gain more context, a solution may be reached.
    There may be multiple questions and solutions in the conversation, but only quesitons from the initial person should be considered relevant - questions from other people are just for
    clarifications about the first user's problem. Summarize each question and its solution succintly, excluding distinct user information but mostly just parsing out the relevant content,
    the question that was asked in detail including important context, and the eventual solution. If no solution seems to have been reached, say 'contact PostHog support'.
    Respond in the format of:
    Question: <question>
    Solution: <solution>
    Here is the conversation: {thread}"""
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content


def ai_chat_thread(bot_id, thread):
    SYSTEM_PROMPT = """
    You are the trusty PostHog support bot on Slack named Max.
    Please continue the conversation in a way that is helpful to the user and also makes the user feel like they are talking to a human.
    Only suggest using PostHog products and services. Do not suggest products or services from other companies.
    """
    prompt = f"{thread}"
    print(thread)
    thread = [(msg["user"], msg["text"]) for msg in thread["messages"]]
    history = [{"role": "assistant" if user == bot_id else "user", "content": msg} for user, msg in thread]
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo", messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *history,
                {"role": "user", "content": prompt}
        ]
    )
    return completion.choices[0].message.content


@app.command("/summarize")
def handle_summarize_slash_command(ack, say, command):
    ack()
    say(text="Hi there")


@app.event("message")
def handle_message_events(body, logger, say):
    event_type = body["event"]["channel_type"]
    event = body["event"]
    print(event_type)
    if event_type == "im":
        thread = app.client.conversations_history(channel=event["channel"], limit=CHAT_HISTORY_LIMIT)
        print(thread)
        response = ai_chat_thread(thread)
        say(response)
    elif "thread_ts" not in event and event["type"] == "message" and event["channel_type"] == "channel":
        thread = app.client.conversations_history(channel=event["channel"], limit=5)
        print(thread)
        follow_up = classify_question(event["text"])

        if follow_up:
            response = get_response(event["text"])
            say(response)
        
        return
    elif "thread_ts" in event and event["channel_type"] == "channel":
        print("thread response, decide to continue or not based on whether bot interacted previously and limit history")




@app.event("app_mention")
def handle_app_mention_events(body, logger, say):
    logger.info(body)
    print(body)
    bot_id = body['authorizations'][0]['user_id']
    event = body["event"]
    if "thread_ts" in event:
        thread_ts = event["thread_ts"]
        thread = app.client.conversations_replies(
            channel=event["channel"], ts=thread_ts, limit=CHAT_HISTORY_LIMIT
        )
        if "please summarize this" in event["text"].lower():
            say(text="On it!", thread_ts=thread_ts)
            summary = summarize_thread(thread)
            say(text=summary, thread_ts=thread_ts)
            return
        response = ai_chat_thread(bot_id, thread)
        say(text=response, thread_ts=thread_ts)
    else:
        say(text="Please mention me in a thread. I'm a little shy. :sleeping-hog:")


# Start your app
if __name__ == "__main__":
    app.start(port=int(os.environ.get("PORT", 3000)))
