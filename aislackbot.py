# load creds/keys from env
import dotenv, os
dotenv.load_dotenv()

# dependencies for slack
from slack_bolt import App
from flask import Flask, request, jsonify
from slack_bolt.adapter.flask import SlackRequestHandler

# dependencies for RAG
from llama_index import VectorStoreIndex, StorageContext
from llama_index.vector_stores import AstraDBVectorStore

# initialise vector store with Astra DB
vector_store = AstraDBVectorStore(
    token=os.environ.get("ASTRA_DB_APPLICATION_TOKEN"),
    api_endpoint=os.environ.get("ASTRA_DB_API_ENDPOINT"),
    collection_name=os.environ.get("ASTRA_DB_TABLE_NAME"),
    embedding_dimension=1536,
)
storage_context = StorageContext.from_defaults(vector_store=vector_store)
index = VectorStoreIndex.from_vector_store(
    vector_store=vector_store, storage_context=storage_context
)

# Initialize Bolt app with token and secret
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)
handler = SlackRequestHandler(app)
flask_app = Flask(__name__)

# join the #bot-testing channel so we can listen to messages
channel_list = app.client.conversations_list().data
channel = next((channel for channel in channel_list.get('channels') if channel.get("name") == "bot-testing"), None)
channel_id = channel.get('id')
app.client.conversations_join(channel=channel_id)
print(f"Found the channel {channel_id} and joined it")

# get the bot's own user ID so it can tell when somebody is mentioning it
auth_response = app.client.auth_test()
bot_user_id = auth_response["user_id"]

# this is the challenge route required by Slack
# if it's not the challenge it's something for Bolt to handle
@flask_app.route("/", methods=["POST"])
def slack_challenge():
    if request.json and "challenge" in request.json:
        print("Received challenge")
        return jsonify({"challenge": request.json["challenge"]})
    else:
        print("Incoming event:")
        print(request.json)
    return handler.handle(request)

# this handles any incoming message the bot can hear
# we want it to only respond when somebody messages it directly
# otherwise it listens and stores every message as future context
@app.message()
def reply(message, say):
    # the slack message object is a complicated nested object
    # if message contains a "blocks" key
    #   then look for a "block" with the type "rich text"
    #       if you find it 
    #       then look inside that block for an "elements" key
    #           if you find it 
    #               then examine each one of those for an "elements" key
    #               if you find it
    #                   then look inside each "element" for one with type "user"
    #                   if you find it  
    #                   and if that user matches the bot_user_id 
    #                       then it's a message for the bot
    if message.get('blocks'):
        for block in message.get('blocks'):
            if block.get('type') == 'rich_text':
                for rich_text_section in block.get('elements'):
                    for element in rich_text_section.get('elements'):
                        if element.get('type') == 'user' and element.get('user_id') == bot_user_id:
                            for element in rich_text_section.get('elements'):
                                if element.get('type') == 'text':
                                    query = element.get('text')
                                    query_engine = index.as_query_engine()
                                    response = query_engine.query(query)
                                    say(str(response))
                                    return
    # otherwise do something else with it
    print("Saw a fact: ", message.get('text'))

if __name__ == "__main__":
    flask_app.run(port=3000)