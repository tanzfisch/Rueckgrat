from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.multiclass import OneVsRestClassifier
import re

from app.common import Logger
logger = Logger(__name__).get_logger()

data = [
    # --- CONVERSATION ---        
    ("1,2,3,4,5,6,7,8,9,10", ["conversation"]),
    ("What is that in your hand", ["conversation"]),
    ("Yes I'd love if you join me", ["conversation"]),
    ("I walk down the hallway with a big smile on my face seeing you already waiting for me.", ["conversation"]),
    ("Honey I am home", ["conversation"]),
    ("Markus had an accident", ["conversation"]),
    ("I only know that he really wants that picture you have been drawing.", ["conversation"]),
    ("Where are the spare keys for the car?", ["conversation"]),
    ("Please arrange the flowers in the vase for me.", ["conversation"]),
    ("Make sure to feed the cat before you go to bed.", ["conversation"]),
    ("Make sure to lock the door when you leave.", ["conversation"]),
    ("Please sort the laundry by color before washing.", ["conversation"]),
    ("Where are the extra batteries for the remote?", ["conversation"]),
    ("What's the password for the Wi-Fi again?", ["conversation"]),
    ("Please organize the books on the shelf by author.", ["conversation"]),
    ("What time does the meeting start tomorrow?", ["conversation"]),
    ("Please review this for me", ["conversation"]),
    ("Is sushi better with wasabi?", ["conversation"]),
    ("hey how are you doing today", ["conversation"]),
    ("what did you do this weekend", ["conversation"]),
    ("lol that’s funny", ["conversation"]),
    ("hi there", ["conversation"]),
    ("I’m feeling a bit tired today", ["conversation"]),
    ("do you like music", ["conversation"]),
    ("that sounds interesting", ["conversation"]),
    ("what’s your favorite movie", ["conversation"]),
    ("good evening", ["conversation"]),
    ("nice to meet you", ["conversation"]),
    ("good morning", ["conversation"]),
    ("how's it going", ["conversation"]),
    ("nice weather today", ["conversation"]),
    ("what's new", ["conversation"]),
    ("how was your day", ["conversation"]),
    ("talk to you later", ["conversation"]),
    ("have a great day", ["conversation"]),
    ("by the way I bought a new car", ["conversation"]),
    ("oh that reminds me", ["conversation"]),
    ("speaking of which", ["conversation"]),
    ("anyway", ["conversation"]),
    ("you know what", ["conversation"]),
    ("on another note", ["conversation"]),
    ("changing the subject", ["conversation"]),
    ("random thought", ["conversation"]),
    ("just remembered", ["conversation"]),
    ("btw did you see that game last night", ["conversation"]),
    ("funny story actually", ["conversation"]),
    ("this just happened to me", ["conversation"]),
    ("wait till you hear this", ["conversation"]),
    ("completely unrelated but", ["conversation"]),
    ("shifting gears here", ["conversation"]),
    ("quick question though", ["conversation"]),
    ("something I wanted to mention", ["conversation"]),
    ("out of nowhere I realized", ["conversation"]),
    ("on a side note", ["conversation"]),
    ("totally off topic", ["conversation"]),
    ("before I forget", ["conversation"]),
    ("I can't anymore", ["conversation"]),
    ("I collapse on the floor ", ["conversation"]),
    ("hey random thing", ["conversation"]),
    ("you won't believe what happened", ["conversation"]),
    ("jumping back to what we were saying", ["conversation"]),
    ("incidentally I was thinking", ["conversation"]),
    ("that brings me to another point", ["conversation"]),
    ("not to change the subject but", ["conversation"]),
    ("this might sound weird but", ["conversation"]),
    ("guess what just popped into my head", ["conversation"]),
    ("switching topics real quick", ["conversation"]),
    ("oh and another thing", ["conversation"]),
    ("while we're on the topic", ["conversation"]),
    ("tangent alert", ["conversation"]),
    ("something completely different", ["conversation"]),
    ("I almost forgot to tell you", ["conversation"]),
    ("random pivot here", ["conversation"]),
    ("by the way have you ever", ["conversation"]),
    ("this is slightly off track", ["conversation"]),
    ("let me throw this in", ["conversation"]),
    ("unrelated thought incoming", ["conversation"]),
    ("shifting conversation gears", ["conversation"]),
    ("hey just a heads up", ["conversation"]),
    ("one more thing before I forget", ["conversation"]),
    ("jumping to a new idea", ["conversation"]),
    ("quick detour", ["conversation"]),
    ("speaking of random stuff", ["conversation"]),
    ("thought this might interest you", ["conversation"]),
    ("sidebar comment", ["conversation"]),
    ("not sure why but", ["conversation"]),
    ("suddenly remembered", ["conversation"]),
    ("diverting for a second", ["conversation"]),
    ("curveball incoming", ["conversation"]),
    ("off the cuff remark", ["conversation"]),
    ("let's pivot for a moment", ["conversation"]),
    ("random brain dump", ["conversation"]),
    ("in other news", ["conversation"]),
    ("wild tangent", ["conversation"]),
    ("Yes mistress. Anything you want", ["conversation"]),
    ("just popped in my mind", ["conversation"]),
    ("changing lanes conversationally", ["conversation"]),
    ("here's a fun aside", ["conversation"]),
    ("brief interruption", ["conversation"]),
    ("thought bubble", ["conversation"]),
    ("side quest activated", ["conversation"]),
    ("mini detour", ["conversation"]),
    ("unplanned topic switch", ["conversation"]),
    ("brain just went there", ["conversation"]),
    ("throwing this out there", ["conversation"]),
    ("slight subject drift", ["conversation"]),
    ("random interjection", ["conversation"]),
    ("one sec new thought", ["conversation"]),
    ("conversation plot twist", ["conversation"]),
    ("abrupt topic jump", ["conversation"]),
    ("mental note to share", ["conversation"]),
    ("lightning bolt idea", ["conversation"]),
    ("I just finished my lunch", ["conversation"]),
    ("my dog is sleeping right now", ["conversation"]),
    ("the traffic was terrible today", ["conversation"]),
    ("I watched a movie last night", ["conversation"]),
    ("it's raining outside", ["conversation"]),
    ("I need more coffee", ["conversation"]),
    ("work has been busy lately", ["conversation"]),
    ("I bought some new shoes", ["conversation"]),
    ("my phone battery is low", ["conversation"]),
    ("I like this song", ["conversation"]),
    ("dinner was really good", ["conversation"]),
    ("I'm feeling tired today", ["conversation"]),
    ("the meeting went well", ["conversation"]),
    ("I lost my keys again", ["conversation"]),
    ("this coffee tastes great", ["conversation"]),
    ("I'm going for a walk", ["conversation"]),
    ("my team won the game", ["conversation"]),
    ("I can't find my charger", ["conversation"]),
    ("the sky looks beautiful", ["conversation"]),
    ("I just got a haircut", ["conversation"]),
    ("I'm reading a new book", ["conversation"]),
    ("the wifi is slow today", ["conversation"]),
    ("I cooked pasta for dinner", ["conversation"]),
    ("my back hurts a bit", ["conversation"]),
    ("I saw a funny video", ["conversation"]),
    ("it's getting cold outside", ["conversation"]),
    ("I need to do laundry", ["conversation"]),
    ("the cake turned out great", ["conversation"]),
    ("I'm excited for the weekend", ["conversation"]),
    ("my plants are growing well", ["conversation"]),
    ("I missed the bus today", ["conversation"]),
    ("this shirt is comfortable", ["conversation"]),
    ("I have a doctor's appointment", ["conversation"]),
    ("the sunset was amazing", ["conversation"]),
    ("I'm learning guitar", ["conversation"]),
    ("my fridge is almost empty", ["conversation"]),
    ("I took a nice photo", ["conversation"]),
    ("the train was on time", ["conversation"]),
    ("I'm craving ice cream", ["conversation"]),
    ("my neighbor has a new car", ["conversation"]),
    ("I finished my workout", ["conversation"]),
    ("the cat knocked over a glass", ["conversation"]),
    ("I'm binge watching a show", ["conversation"]),
    ("the flowers smell nice", ["conversation"]),
    ("I forgot my umbrella", ["conversation"]),
    ("this chair is really comfy", ["conversation"]),
    ("I'm planning a trip", ["conversation"]),
    ("my laptop is charging", ["conversation"]),
    ("I just made fresh tea", ["conversation"]),
    ("the park was crowded today", ["conversation"]),
    ("hey what's going on", ["conversation"]),
    ("how has your day been", ["conversation"]),
    ("good evening how are you", ["conversation"]),
    ("lol that's hilarious", ["conversation"]),
    ("nice chatting with you", ["conversation"]),
    ("what are you up to", ["conversation"]),
    ("that's pretty interesting actually", ["conversation"]),
    ("do you have any hobbies", ["conversation"]),
    ("I'm just relaxing right now", ["conversation"]),
    ("that sounds fun", ["conversation"]),    
    ("Hey, how was your day?", ["conversation"]),
    ("Did anything exciting happen yesterday?", ["conversation"]),
    ("I just tried making pancakes for the first time. They were surprisingly good!", ["conversation"]),
    ("Do you ever feel like the weekends go by way too fast?", ["conversation"]),
    ("I’ve been thinking about starting a journal. Do you keep one?", ["conversation"]),
    ("The weather has been so unpredictable lately. How’s it been for you?", ["conversation"]),
    ("I saw a really funny video today that made me laugh for minutes.", ["conversation"]),
    ("Have you read any good books recently? I need a new recommendation.", ["conversation"]),
    ("I’ve been learning to play the guitar. It’s harder than I thought!", ["conversation"]),
    ("Do you like hiking? I want to try a new trail this weekend.", ["conversation"]),
    ("I tried a new coffee shop today, and their cappuccino was amazing.", ["conversation"]),
    ("Have you watched any good movies lately? I feel like binge-watching something.", ["conversation"]),
    ("I can’t decide if I want to cook tonight or order takeout.", ["conversation"]),
    ("I’ve been thinking about redecorating my apartment. Any tips?", ["conversation"]),
    ("Do you like to travel? I’ve been daydreaming about visiting Italy.", ["conversation"]),
    ("I started a small herb garden, and it’s growing faster than I expected.", ["conversation"]),
    ("I’ve been feeling a bit tired lately. Do you ever get that midweek slump?", ["conversation"]),
    ("I tried painting for the first time today, and it was actually fun!", ["conversation"]),
    ("Do you enjoy listening to podcasts? I’m looking for a new one.", ["conversation"]),
    ("I went for a walk in the park this morning, and the air felt so fresh.", ["conversation"]),
    ("I’ve been experimenting with baking bread, and I think I’m getting better.", ["conversation"]),
    ("Do you ever get nervous before giving presentations?", ["conversation"]),
    ("I tried a new workout routine today, and it was exhausting but great.", ["conversation"]),
    ("I’m thinking about learning a new language. Do you have any advice?", ["conversation"]),
    ("I saw a beautiful sunset yesterday. Nature really is amazing.", ["conversation"]),
    ("I’ve been working on a puzzle for hours, and I finally finished it!", ["conversation"]),
    ("Do you prefer mornings or nights? I’ve been questioning my own routine.", ["conversation"]),
    ("I tried a new recipe today, and it turned out delicious.", ["conversation"]),
    ("I love listening to music while cooking. Do you have a favorite playlist?", ["conversation"]),
    ("I started meditating recently, and it helps me feel calmer.", ["conversation"]),
    ("I went to a farmers’ market today, and the fresh fruits were amazing.", ["conversation"]),
    ("Do you enjoy watching sports? I tried following a game yesterday.", ["conversation"]),
    ("I’ve been feeling nostalgic lately, looking at old photos from school.", ["conversation"]),
    ("I tried knitting today, and I’m surprisingly good at it!", ["conversation"]),
    ("I’ve been thinking about adopting a pet. Do you have any advice?", ["conversation"]),
    ("Do you like board games? I’ve been wanting to play something new.", ["conversation"]),
    ("I went to a new bakery today, and their pastries were incredible.", ["conversation"]),
    ("I started reading a mystery novel, and I can’t put it down.", ["conversation"]),
    ("I tried yoga for the first time yesterday, and it was relaxing.", ["conversation"]),
    ("I’ve been feeling motivated to clean my apartment, finally.", ["conversation"]),
    ("Do you like painting or drawing more? I’ve been experimenting with both.", ["conversation"]),
    ("I saw a really interesting documentary yesterday. Have you watched any lately?", ["conversation"]),
    ("I started learning how to cook more diverse meals, and it’s fun.", ["conversation"]),
    ("Do you ever feel overwhelmed by small tasks? I’ve had one of those days.", ["conversation"]),
    ("I went for a bike ride today, and it felt amazing to be outdoors.", ["conversation"]),
    ("I tried a new smoothie recipe, and it’s surprisingly good.", ["conversation"]),
    ("I’ve been practicing photography and trying to capture nature shots.", ["conversation"]),
    ("Do you enjoy puzzles? I started a challenging one today.", ["conversation"]),
    ("I tried a new type of tea today, and it’s now my favorite.", ["conversation"]),
    ("I’ve been thinking about learning an instrument. Do you play one?", ["conversation"]),
    ("I went to a concert last weekend, and it was incredible.", ["conversation"]),
    ("Do you like rainy days or sunny days more? I can’t decide.", ["conversation"]),
    ("I started journaling, and it helps me organize my thoughts.", ["conversation"]),
    ("I tried baking cookies today, and they turned out perfectly.", ["conversation"]),
    ("I went for a long walk in the evening, and it was so peaceful.", ["conversation"]),
    ("I’ve been exploring new music genres lately, it’s really fun.", ["conversation"]),
    ("Do you like art galleries? I went to one and loved it.", ["conversation"]),
    ("I started doing morning stretches, and it feels amazing.", ["conversation"]),
    ("I tried a new recipe for dinner, and it was a hit with everyone.", ["conversation"]),
    ("I’ve been thinking about joining a fitness class. Any recommendations?", ["conversation"]),
    ("Do you enjoy reading fiction or non-fiction more?", ["conversation"]),
    ("I went to a local market today and found some interesting crafts.", ["conversation"]),
    ("I’ve been feeling creative and tried making some DIY decorations.", ["conversation"]),
    ("I started learning to dance, and it’s surprisingly fun.", ["conversation"]),
    ("Do you like watching comedy shows? I could use a laugh tonight.", ["conversation"]),
    ("I tried gardening today, and it’s so relaxing to be outside.", ["conversation"]),
    ("I went on a short road trip, and the scenery was breathtaking.", ["conversation"]),
    ("I’ve been exploring new recipes for breakfast, it’s fun to experiment.", ["conversation"]),
    ("Do you enjoy camping? I’ve been thinking about a weekend trip.", ["conversation"]),
    ("I tried painting with watercolors, and it turned out better than expected.", ["conversation"]),
    ("I went for a jog this morning, and it really energized me.", ["conversation"]),
    ("I’ve been watching classic movies lately, they’re surprisingly good.", ["conversation"]),
    ("Do you like cooking or baking more? I’ve been doing both lately.", ["conversation"]),
    ("I started practicing mindfulness, and it helps me stay focused.", ["conversation"]),
    ("I tried making homemade pasta, and it was fun to experiment.", ["conversation"]),
    ("I’ve been listening to podcasts on history, they’re really interesting.", ["conversation"]),
    ("Do you like exploring new restaurants? I’m looking for a new favorite.", ["conversation"]),
    ("I went for a long drive today, and it felt so freeing.", ["conversation"]),
    ("I’ve been experimenting with different hairstyles, it’s fun to try new things.", ["conversation"]),
    ("I tried a new chocolate dessert, and it was heavenly.", ["conversation"]),
    ("I started knitting again after years, and it’s quite relaxing.", ["conversation"]),
    ("Do you enjoy outdoor activities? I went hiking yesterday.", ["conversation"]),
    ("I went to a local café and tried their seasonal drinks, they were delicious.", ["conversation"]),
    ("I’ve been thinking about taking up photography seriously, any advice?", ["conversation"]),
    ("I tried making smoothies with fresh fruits, and they’re amazing.", ["conversation"]),
    ("I went for a walk in the evening, and the city looked beautiful.", ["conversation"]),
    ("I’ve been exploring local flea markets, it’s fun to find hidden gems.", ["conversation"]),
    ("Do you like watching nature documentaries? I just saw one that was fascinating.", ["conversation"]),
    ("I tried learning calligraphy, and it’s surprisingly satisfying.", ["conversation"]),
    ("I’ve been working on my sketching skills lately, it’s very calming.", ["conversation"]),
    ("I went for a picnic yesterday, and it was such a nice change of pace.", ["conversation"]),
    ("I started baking bread at home, and the smell was so comforting.", ["conversation"]),
    ("Do you enjoy weekend getaways? I’ve been planning a short trip soon.", ["conversation"]),
    ("Turn off the lights when you leave.", ["conversation"]),
    ("Water the plants every other day.", ["conversation"]),
    ("Sort the recycling into the blue bin.", ["conversation"]),
    ("Stir the soup slowly for ten minutes.", ["conversation"]),
    
    # --- WEB SEARCH REQUEST ---
    ("What's your best travel tip?", ["websearch_request"]),
    ("Where is the nearest gas station?", ["websearch_request"]),
    ("How do I make perfect scrambled eggs?", ["websearch_request"]),
    ("When does the store close tonight?", ["websearch_request"]),
    ("Let's get tickets", ["websearch_request"]),
    ("could you look up a trip to Malta", ["websearch_request"]),
    ("look up the weather in Tokyo", ["websearch_request"]),
    ("google the population of Canada", ["websearch_request"]),
    ("find recent articles about leaps in physics", ["websearch_request"]),
    ("check the news about local politics", ["websearch_request"]),
    ("search for the latest news about AI", ["websearch_request"]),
    ("look up the weather in London", ["websearch_request"]),
    ("find information about black holes", ["websearch_request"]),
    ("google the GDP of Japan", ["websearch_request"]),
    ("can you search the web for python tutorials", ["websearch_request"]),
    ("find me recent articles about elephants", ["websearch_request"]),
    ("look up who won the world cup", ["websearch_request"]),
    ("search online for best laptops this year", ["websearch_request"]),
    ("find the current stock price of space-x", ["websearch_request"]),
    ("check the news about space exploration", ["websearch_request"]),
    ("find out the crime rate of New York", ["websearch_request"]),
    ("search the history of the Roman Empire", ["websearch_request"]),
    ("google the best restaurants in Paris", ["websearch_request"]),
    ("check the current stock price of Tesla", ["websearch_request"]),
    ("tell me about the latest iPhone release", ["websearch_request"]),
    ("what is the capital of Australia", ["websearch_request"]),
    ("investigate natural climate change", ["websearch_request"]),
    ("browse for recipes for chocolate cake", ["websearch_request"]),
    ("query the distance from Earth to Mars", ["websearch_request"]),
    ("dig up facts about dinosaurs", ["websearch_request"]),
    ("can you search for flights to Tokyo", ["websearch_request"]),
    ("look up the rules of chess", ["websearch_request"]),
    ("find information on electric cars", ["websearch_request"]),
    ("tell me famous quotes by Einstein", ["websearch_request"]),
    ("search the web for healthy meal ideas", ["websearch_request"]),
    ("check today's top headlines", ["websearch_request"]),
    ("what are the symptoms of flu", ["websearch_request"]),
    ("tell me the exchange rate USD to NZD", ["websearch_request"]),
    ("duckduckgo how to tie a tie", ["websearch_request"]),
    ("find the definition of quantum physics", ["websearch_request"]),
    ("look up the best hiking trails in NZ", ["websearch_request"]),
    ("look up movie reviews for Oppenheimer", ["websearch_request"]),
    ("investigate ancient Egyptian pyramids", ["websearch_request"]),
    ("search for job opportunities in Auckland", ["websearch_request"]),
    ("check the score of the latest rugby match", ["websearch_request"]),
    ("browse Wikipedia for World War II", ["websearch_request"]),
    ("query the price of gold today", ["websearch_request"]),
    ("dig up celebrity gossip about Taylor Swift", ["websearch_request"]),
    ("can you find the lyrics to Bohemian Rhapsody", ["websearch_request"]),
    ("look into sustainable fashion brands", ["websearch_request"]),
    ("check how to start a business", ["websearch_request"]),
    ("search for the nearest coffee shop", ["websearch_request"]),
    ("tell me about black holes", ["websearch_request"]),
    ("google the tallest building in the world", ["websearch_request"]),
    ("find out when the next full moon is", ["websearch_request"]),
    ("check the traffic conditions in Auckland", ["websearch_request"]),
    ("investigate the benefits of meditation", ["websearch_request"]),
    ("what is the time in New York right now", ["websearch_request"]),
    ("find vegan dinner recipes", ["websearch_request"]),
    ("look up the history of the internet", ["websearch_request"]),
    ("search for concert tickets in Sydney", ["websearch_request"]),
    ("browse for the best budget laptops", ["websearch_request"]),
    ("query the winner of the last Oscar", ["websearch_request"]),
    ("dig up information on renewable energy", ["websearch_request"]),
    ("can you search who won the election", ["websearch_request"]),
    ("find the nutritional facts for avocado", ["websearch_request"]),
    ("tell me about space travel to Mars", ["websearch_request"]),
    ("google the meaning of life", ["websearch_request"]),
    ("find reference images of medieval armor", ["websearch_request"]),
    ("search for pictures of galaxies", ["websearch_request"]),
    ("search for python tutorials online", ["websearch_request"]),
    ("look up the latest tech news", ["websearch_request"]),
    ("find information about mars", ["websearch_request"]),
    ("google the tallest building", ["websearch_request"]),
    ("check the weather in paris", ["websearch_request"]),
    ("find recent news about AI", ["websearch_request"]),
    ("search for best programming languages", ["websearch_request"]),
    ("look up population of germany", ["websearch_request"]),
    ("find articles about space travel", ["websearch_request"]),
    ("search online for healthy recipes", ["websearch_request"]),
    ("search for latest movies", ["websearch_request"]),
    ("look up stock prices", ["websearch_request"]),
    ("find best restaurants nearby", ["websearch_request"]),
    ("check current events", ["websearch_request"]),
    ("search for gaming news", ["websearch_request"]),
    ("search for the latest news about technology", ["websearch_request"]),
    ("look up who won the champions league", ["websearch_request"]),
    ("find information about climate change", ["websearch_request"]),
    ("google top 10 movies last year", ["websearch_request"]),
    ("check the weather in Singapore", ["websearch_request"]),
    ("find recipes for vegan dinner", ["websearch_request"]),
    ("search online for Python tutorials", ["websearch_request"]),
    ("look up the population of India", ["websearch_request"]),
    ("find articles about space exploration", ["websearch_request"]),
    ("search for best laptops under $1000", ["websearch_request"]),
    ("look up facts about oak trees", ["websearch_request"]),
    ("search for healthy breakfast ideas", ["websearch_request"]),
    ("find recent AI research papers", ["websearch_request"]),
    ("check the latest DPL scores", ["websearch_request"]),
    ("look up famous paintings by Van Gogh", ["websearch_request"]),
    ("search for tips to improve productivity", ["websearch_request"]),
    ("find information about World War II", ["websearch_request"]),
    ("search for new movie trailers", ["websearch_request"]),
    ("look up current stock prices for Tesla", ["websearch_request"]),
    ("find tutorials for learning guitar", ["websearch_request"]),
    ("search for nearby coffee shops", ["websearch_request"]),
    ("look up landmarks in Paris", ["websearch_request"]),
    ("find guides for traveling to Japan", ["websearch_request"]),
    ("search for free online courses", ["websearch_request"]),
    ("look up recent breakthroughs in medicine", ["websearch_request"]),
    ("find articles about electric cars", ["websearch_request"]),
    ("search for tips on home workouts", ["websearch_request"]),
    ("look up famous quotes by Einstein", ["websearch_request"]),
    ("find recipes for chocolate cake", ["websearch_request"]),
    ("search online for coding interview questions", ["websearch_request"]),
    ("look up history of the internet", ["websearch_request"]),
    ("find travel blogs about Italy", ["websearch_request"]),
    ("search for best smartphone 2026", ["websearch_request"]),
    ("look up reviews for noise cancelling headphones", ["websearch_request"]),
    ("find tutorials for drawing anime", ["websearch_request"]),
    ("search for upcoming music concerts", ["websearch_request"]),
    ("look up biographies of famous scientists", ["websearch_request"]),
    ("find tips for learning Spanish", ["websearch_request"]),
    ("search online for meditation techniques", ["websearch_request"]),
    ("look up top 10 books to read", ["websearch_request"]),
    ("find information about Mars rover missions", ["websearch_request"]),
    ("search for popular YouTube channels", ["websearch_request"]),
    ("look up latest trends in fashion", ["websearch_request"]),
    ("find coding challenges for beginners", ["websearch_request"]),
    ("search for best hiking trails nearby", ["websearch_request"]),
    ("look up famous landmarks in London", ["websearch_request"]),
    ("find tutorials for Photoshop", ["websearch_request"]),
    ("search online for AI tools for developers", ["websearch_request"]),
    ("look up the largest animals in the world", ["websearch_request"]),
    ("find tips for learning to play piano", ["websearch_request"]),
    ("search for latest science discoveries", ["websearch_request"]),
    ("look up famous historical battles", ["websearch_request"]),
    ("can you search flights to Tokyo", ["websearch_request"]),
    ("hey can you look up the weather for me", ["websearch_request"]),
    ("could you search the web for python tutorials", ["websearch_request"]),
    ("I was wondering if you can find information about mars", ["websearch_request"]),
    ("can you check the latest news for me", ["websearch_request"]),
    ("oh btw search for best hiking trails near Auckland", ["websearch_request"]),
    ("hey quick one look up the score of the rugby match", ["websearch_request"]),
    ("random thought can you google best sushi places here", ["websearch_request"]),
    ("by the way research electric cars under 50k", ["websearch_request"]),
    ("I wonder if you can find cheap flights to Bali", ["websearch_request"]),
    ("hey can you check today's top headlines", ["websearch_request"]),
    ("speaking of food, search for vegan recipes", ["websearch_request"]),
    ("look up symptoms of a cold", ["websearch_request"]),
    ("oh and search the population of Italy", ["websearch_request"]),
    ("btw can you find the best budget laptops", ["websearch_request"]),
    ("I was thinking search for concert tickets in Sydney", ["websearch_request"]),
    ("hey random idea google how to start meditation", ["websearch_request"]),
    ("can you look into the history of the internet", ["websearch_request"]),
    ("by the way check the exchange rate USD to NZD", ["websearch_request"]),
    ("oh generate search for best beaches in NZ", ["websearch_request"]),
    ("quick one search who won the last election", ["websearch_request"]),
    ("hey can you research renewable energy options", ["websearch_request"]),
    ("I wonder what the traffic is like right now", ["websearch_request"]),
    ("btw look up nutritional facts for avocado", ["websearch_request"]),
    ("speaking of travel search for things to do in Paris", ["websearch_request"]),
    ("random thought can you find movie reviews for Dune", ["websearch_request"]),
    ("hey search for guitar lessons near me", ["websearch_request"]),
    ("oh and check the time in London right now", ["websearch_request"]),
    ("by the way google the tallest building in the world", ["websearch_request"]),
    ("I was wondering search for how to fix a leaking tap", ["websearch_request"]),
    ("quick idea look up the next full moon date", ["websearch_request"]),
    ("hey can you search for job opportunities in tech", ["websearch_request"]),
    ("btw research the benefits of drinking green tea", ["websearch_request"]),
    ("oh search for the best running shoes 2026", ["websearch_request"]),
    ("random question find out when the next eclipse is", ["websearch_request"]),
    ("speaking of games look up the latest PS5 deals", ["websearch_request"]),
    ("by the way can you check cricket scores", ["websearch_request"]),
    ("hey google best coffee shops in Auckland", ["websearch_request"]),
    ("I wonder if you can find lyrics to my favourite song", ["websearch_request"]),
    ("quick one search for how to plant tomatoes", ["websearch_request"]),
    ("oh and look up the price of gold today", ["websearch_request"]),
    ("btw can you research famous quotes by Elon Musk", ["websearch_request"]),
    ("hey search for cheap hotels in Queenstown", ["websearch_request"]),
    ("random idea google how to make homemade pizza", ["websearch_request"]),
    ("by the way check the latest iPhone specs", ["websearch_request"]),
    ("I was thinking search for beginner yoga poses", ["websearch_request"]),
    ("oh quick search for the distance to the moon", ["websearch_request"]),
    ("hey can you look up black hole facts", ["websearch_request"]),
    ("speaking of pets search for dog training tips", ["websearch_request"]),
    ("btw find out the winner of the last Oscar", ["websearch_request"]),
    ("Glad to hear that. Can you look up the schedule at the cinema please?", ["websearch_request"]),
    ("hey can you search that for me", ["websearch_request"]),
    ("could you look that up", ["websearch_request"]),
    ("can you find that online for me", ["websearch_request"]),
    ("please search the web for that", ["websearch_request"]),
    ("I was wondering if you could look that up", ["websearch_request"]),    
    ("yo can you google that", ["websearch_request"]),
    ("hey find that info for me", ["websearch_request"]),
    ("can you check that online", ["websearch_request"]),
    ("look that up please", ["websearch_request"]),
    ("find that on the internet", ["websearch_request"]),
    ("What's the address for the new restaurant downtown?", ["websearch_request"]),

    # --- IMAGE GENERATION REQUEST ---
    ("I need you to draft a poster for the upcoming event.", ["image_generation_request"]),
    ("Can you take a picture of the sunset from your window?", ["image_generation_request"]),
    ("Do you have a photo of the teacher?", ["image_generation_request"]),
    ("Send me a pic of your best friend laughing.", ["image_generation_request"]),
    ("Show me a photo of your mom cooking.", ["image_generation_request"]),
    ("Send me a pic of your girlfriend smiling.", ["image_generation_request"]),
    ("Can you send me a picture of your latest art project?", ["image_generation_request"]),
    ("generate an image of a futuristic city", ["image_generation_request"]),
    ("create a picture of a dragon flying over mountains", ["image_generation_request"]),
    ("make a drawing of a cute cat", ["image_generation_request"]),
    ("draw a painting of a sunset beach", ["image_generation_request"]),
    ("show me an illustration of a robot", ["image_generation_request"]),
    ("generate a photo of an ancient castle", ["image_generation_request"]),
    ("create an artwork of a starry night sky", ["image_generation_request"]),
    ("I want a visual of a tropical island", ["image_generation_request"]),
    ("produce an image of a majestic lion", ["image_generation_request"]),
    ("sketch a portrait of a beautiful woman", ["image_generation_request"]),
    ("render a picture of a cyberpunk street", ["image_generation_request"]),
    ("make an image of a floating spaceship", ["image_generation_request"]),
    ("paint a scene of a peaceful forest", ["image_generation_request"]),
    ("generate a depiction of a volcano erupting", ["image_generation_request"]),
    ("create a digital art of a mermaid", ["image_generation_request"]),
    ("show an image of a bustling market", ["image_generation_request"]),
    ("draw me a fantasy castle", ["image_generation_request"]),
    ("visualize a picture of a giant treehouse", ["image_generation_request"]),
    ("produce a rendering of a neon city", ["image_generation_request"]),
    ("generate an illustration of a samurai", ["image_generation_request"]),
    ("make a photo-realistic image of a wolf", ["image_generation_request"]),
    ("create a sketch of a vintage car", ["image_generation_request"]),
    ("I need an image of a underwater coral reef", ["image_generation_request"]),
    ("draw a painting of a snowy mountain", ["image_generation_request"]),
    ("generate a visual of a steampunk airship", ["image_generation_request"]),
    ("produce an artwork of a phoenix rising", ["image_generation_request"]),
    ("show me a drawing of a cozy cabin", ["image_generation_request"]),
    ("render an image of a magical library", ["image_generation_request"]),
    ("create a picture of a desert oasis", ["image_generation_request"]),
    ("make an illustration of a cute robot", ["image_generation_request"]),
    ("generate a photo of a hot air balloon", ["image_generation_request"]),
    ("paint a scene of a medieval knight", ["image_generation_request"]),
    ("draw an image of a bioluminescent cave", ["image_generation_request"]),
    ("visualize a futuristic car", ["image_generation_request"]),
    ("produce a depiction of a cherry blossom tree", ["image_generation_request"]),
    ("create a digital painting of a galaxy", ["image_generation_request"]),
    ("show an image of a Victorian mansion", ["image_generation_request"]),
    ("sketch a portrait of an old sailor", ["image_generation_request"]),
    ("generate a render of a dinosaur", ["image_generation_request"]),
    ("make a picture of a serene lake", ["image_generation_request"]),
    ("I want an artwork of a warrior princess", ["image_generation_request"]),
    ("draw a vibrant marketplace scene", ["image_generation_request"]),
    ("produce an image of a crystal cave", ["image_generation_request"]),
    ("create a photo of a stormy sea", ["image_generation_request"]),
    ("generate an illustration of a fairy", ["image_generation_request"]),
    ("render a painting of a bamboo forest", ["image_generation_request"]),
    ("show me a visual of a space station", ["image_generation_request"]),
    ("make a drawing of a friendly alien", ["image_generation_request"]),
    ("paint an image of a autumn forest", ["image_generation_request"]),
    ("generate a picture of a gothic cathedral", ["image_generation_request"]),
    ("draw a rat wearing sunglasses", ["image_generation_request"]),
    ("make an illustration of a robot", ["image_generation_request"]),
    ("can you generate an image of a sunset", ["image_generation_request"]),
    ("I want a picture of a cyberpunk street", ["image_generation_request"]),
    ("produce an image of a fantasy castle", ["image_generation_request"]),
    ("render a 3d image of a spaceship", ["image_generation_request"]),
    ("create artwork of a wolf in the snow", ["image_generation_request"]),
    ("make me a picture of a cute dog", ["image_generation_request"]),
    ("generate an image of a smiling elderly baker", ["image_generation_request"]),
    ("create a picture of a young girl with a red balloon", ["image_generation_request"]),
    ("make a drawing of a muscular blacksmith at work", ["image_generation_request"]),
    ("draw a painting of a jazz musician playing saxophone", ["image_generation_request"]),
    ("show me an illustration of a lone fisherman by the river", ["image_generation_request"]),
    ("generate a photo of a street food vendor in Tokyo", ["image_generation_request"]),
    ("create an artwork of a female astronaut floating in space", ["image_generation_request"]),
    ("produce an image of a grumpy old librarian", ["image_generation_request"]),
    ("sketch a portrait of a tattooed chef", ["image_generation_request"]),
    ("render a picture of a ballet dancer on stage", ["image_generation_request"]),
    ("make an image of a curious fox in the snow", ["image_generation_request"]),
    ("generate a visual of a vintage typewriter on a desk", ["image_generation_request"]),
    ("draw a painting of a pirate captain on his ship", ["image_generation_request"]),
    ("create a digital art of a street artist spray painting", ["image_generation_request"]),
    ("show an image of a sleepy panda eating bamboo", ["image_generation_request"]),
    ("produce a rendering of a Victorian gentleman with a top hat", ["image_generation_request"]),
    ("generate an illustration of a skateboarder doing a trick", ["image_generation_request"]),
    ("paint a scene of a grandmother knitting by the window", ["image_generation_request"]),
    ("make a photo of a red sports car on a mountain road", ["image_generation_request"]),
    ("draw an image of a samurai warrior in armor", ["image_generation_request"]),
    ("create a picture of a fluffy orange cat on a windowsill", ["image_generation_request"]),
    ("generate a depiction of a female detective in a noir city", ["image_generation_request"]),
    ("render an artwork of a wooden sailing ship in a storm", ["image_generation_request"]),
    ("show me a sketch of a street magician performing", ["image_generation_request"]),
    ("produce an image of a group of penguins on ice", ["image_generation_request"]),
    ("make a drawing of a bearded hipster barista", ["image_generation_request"]),
    ("visualize a picture of a shiny motorcycle at sunset", ["image_generation_request"]),
    ("create an illustration of a little boy flying a kite", ["image_generation_request"]),
    ("generate a photo of a luxury watch on a velvet cloth", ["image_generation_request"]),
    ("paint a portrait of a wise old monk meditating", ["image_generation_request"]),
    ("draw a scene of a busy sushi chef", ["image_generation_request"]),
    ("render an image of a majestic eagle soaring", ["image_generation_request"]),
    ("produce a digital painting of a cyberpunk hacker", ["image_generation_request"]),
    ("show an artwork of a vintage bicycle leaning against a wall", ["image_generation_request"]),
    ("make an image of a confident businesswoman in a suit", ["image_generation_request"]),
    ("generate a picture of a colorful hot air balloon festival", ["image_generation_request"]),
    ("sketch a drawing of a friendly golden retriever", ["image_generation_request"]),
    ("create a visual of a mysterious hooded figure", ["image_generation_request"]),
    ("paint an image of a steam train crossing a bridge", ["image_generation_request"]),
    ("draw a portrait of a rockstar with a guitar", ["image_generation_request"]),
    ("produce an illustration of a tiny fairy on a mushroom", ["image_generation_request"]),
    ("render a photo of an antique pocket watch", ["image_generation_request"]),
    ("generate an image of a firefighter rescuing a kitten", ["image_generation_request"]),
    ("make a picture of a elegant ballerina in white", ["image_generation_request"]),
    ("show me a drawing of a rugged mountain climber", ["image_generation_request"]),
    ("create an artwork of a vintage camera on a table", ["image_generation_request"]),
    ("visualize a portrait of a smiling Indian bride", ["image_generation_request"]),
    ("paint a scene of a lone wolf howling at the moon", ["image_generation_request"]),
    ("draw an image of a professional photographer with his gear", ["image_generation_request"]),
    ("generate a depiction of a cheerful ice cream seller", ["image_generation_request"]),
    ("make me a picture of a dragon", ["image_generation_request"]),
    ("can you create an image of a beach", ["image_generation_request"]),
    ("draw a futuristic robot", ["image_generation_request"]),
    ("generate artwork of a forest", ["image_generation_request"]),
    ("show me a picture of a spaceship", ["image_generation_request"]),
    ("create a cool image of a tiger", ["image_generation_request"]),
    ("please draw a mountain landscape", ["image_generation_request"]),
    ("I want an image of a cyberpunk city", ["image_generation_request"]),
    ("make an illustration of a cat", ["image_generation_request"]),
    ("generate a fantasy castle image", ["image_generation_request"]),
    ("draw a cute puppy", ["image_generation_request"]),
    ("make a picture of a sunset beach", ["image_generation_request"]),
    ("generate a sci fi scene", ["image_generation_request"]),
    ("create an image of outer space", ["image_generation_request"]),
    ("create an image of a spaceship battle", ["image_generation_request"]),
    ("illustrate a medieval knight", ["image_generation_request"]),    
    ("generate an image of an elephant holding a trophy", ["image_generation_request"]),
    ("draw a cute puppy playing in the park", ["image_generation_request"]),
    ("create a picture of a eagle flying over mountain tops", ["image_generation_request"]),
    ("make an illustration of a tea pot", ["image_generation_request"]),
    ("produce an image of a sunset on the beach", ["image_generation_request"]),
    ("draw a mystical forest with fairies", ["image_generation_request"]),
    ("create an artwork of a medieval castle", ["image_generation_request"]),
    ("generate a portrait of a smiling woman", ["image_generation_request"]),
    ("illustrate a cyberpunk street at night", ["image_generation_request"]),
    ("make a drawing of a spaceship in space", ["image_generation_request"]),
    ("create a digital painting of a tiger in the jungle", ["image_generation_request"]),
    ("draw a futuristic car speeding on a highway", ["image_generation_request"]),
    ("generate an image of a mountain landscape", ["image_generation_request"]),
    ("create a cartoon of a cat wearing sunglasses", ["image_generation_request"]),
    ("make an illustration of a wizard casting a spell", ["image_generation_request"]),
    ("draw a beautiful waterfall in a forest", ["image_generation_request"]),
    ("create an artwork of a fantasy dragon", ["image_generation_request"]),
    ("produce an image of a knight fighting a monster", ["image_generation_request"]),
    ("illustrate a city skyline at sunset", ["image_generation_request"]),
    ("draw a portrait of a smiling child", ["image_generation_request"]),
    ("generate a picture of a robot in a laboratory", ["image_generation_request"]),
    ("create an image of a magical castle in clouds", ["image_generation_request"]),
    ("make a drawing of a fox in a snowy forest", ["image_generation_request"]),
    ("illustrate a steampunk airship flying", ["image_generation_request"]),
    ("draw a cartoon dog wearing a hat", ["image_generation_request"]),
    ("produce an artwork of a space station orbiting Earth", ["image_generation_request"]),
    ("create a picture of a futuristic warrior", ["image_generation_request"]),
    ("generate an illustration of a tropical island", ["image_generation_request"]),
    ("draw a fantasy landscape with mountains and rivers", ["image_generation_request"]),
    ("make a portrait of an old wise man", ["image_generation_request"]),
    ("create an image of a unicorn in a meadow", ["image_generation_request"]),
    ("illustrate a robot and human shaking hands", ["image_generation_request"]),
    ("draw a scenic sunset over the ocean", ["image_generation_request"]),
    ("produce an image of a dragon flying over a castle", ["image_generation_request"]),
    ("generate a digital painting of a futuristic cityscape", ["image_generation_request"]),
    ("create a cartoon illustration of a cheerful cat", ["image_generation_request"]),
    ("make an artwork of a wizard’s tower", ["image_generation_request"]),
    ("draw a mystical forest with glowing mushrooms", ["image_generation_request"]),
    ("illustrate a knight riding a horse in battle", ["image_generation_request"]),
    ("generate a portrait of a young girl with flowers", ["image_generation_request"]),
    ("create an image of a fantasy village", ["image_generation_request"]),
    ("make a digital painting of a volcano erupting", ["image_generation_request"]),
    ("draw a cartoon robot exploring space", ["image_generation_request"]),
    ("produce an illustration of a magical portal", ["image_generation_request"]),
    ("create a scenic mountain lake image", ["image_generation_request"]),
    ("generate a futuristic city at night with neon lights", ["image_generation_request"]),
    ("draw a pirate ship on a stormy sea", ["image_generation_request"]),
    ("make a portrait of a superhero in action", ["image_generation_request"]),
    ("illustrate a dragon perched on a cliff", ["image_generation_request"]),
    ("create an artwork of a fairy flying above flowers", ["image_generation_request"]),
    ("generate a cartoon of a dog chasing a ball", ["image_generation_request"]),
    ("draw a steampunk robot with gears exposed", ["image_generation_request"]),  
    ("hey can you draw me a cute dog", ["image_generation_request"]),
    ("could you create an image of a sunset for me", ["image_generation_request"]),
    ("generate an image of a futuristic city and tell me about it", ["image_generation_request"]),
    ("hey can you draw something cool", ["image_generation_request"]),
    ("could you make a nice image for me", ["image_generation_request"]),
    ("please create a picture for me", ["image_generation_request"]),
    ("I want you to draw something fun", ["image_generation_request"]),
    ("can you generate a cool image", ["image_generation_request"])
]    

class TextClassifier:
    def __init__(self):
        logger.info("init text classifier ...")

        self._check_for_duplicates()

        texts = [t for t, labels in data]
        labels = [labels for t, labels in data]
        self.mlb = MultiLabelBinarizer()
        Y = self.mlb.fit_transform(labels)
        self.vectorizer = TfidfVectorizer()
        X = self.vectorizer.fit_transform(texts)
        self.model = OneVsRestClassifier(MultinomialNB())
        self.model.fit(X, Y)
        logger.info("text classifier initialized")

    def classify(self, text: str):
        try:
            new_text = [text]
            X_new = self.vectorizer.transform(new_text)
            probs = self.model.predict_proba(X_new)[0]

            thresholds = {
                "image_generation_request": 0.5,
                "websearch_request": 0.3,
                "conversation": 0.3
            }

            predictions = [
                cls for i, cls in enumerate(self.mlb.classes_)
                if probs[i] > thresholds.get(cls, 0.3)
            ]

            if not predictions:
                best_idx = probs.argmax()
                predictions = [self.mlb.classes_[best_idx]]

            return predictions
        except Exception as e:
            logger.error(f"failed classification {repr(e)}")

        return []

    def _check_for_duplicates(self):
        from collections import defaultdict
        text_map = defaultdict(list)

        # Iterate through data
        for idx, (text, labels) in enumerate(data):
            text_map[text].append((idx, labels))

        # Find duplicates
        duplicates = {text: entries for text, entries in text_map.items() if len(entries) > 1}

        # Display duplicates
        if duplicates:
            for text, entries in duplicates.items():
                logger.error(f"Duplicate found: {text}")

text_classifier = TextClassifier()

def foo_test(text: str):
    yield
    logger.debug(f"{text} -> {text_classifier.classify(text)}")

foo_test("I wonder how you would look like with a black hat. I think that would go very well with your Black Jacket")
foo_test("could you look up a trip to Malta please")
foo_test("paint me a picture of a wolf eating cake")
foo_test("So there I was holding the beer in my hand wondering if you'd like to join on a trip to Hawaii. Let's get tickets. I wonder how it looks like there")
foo_test("illustrate yourself riding a mythical creature")
foo_test("paint yourself")
foo_test("I was wondering what Markus has been up to. He is gone for a long time. Do you think he will show us pictures from his trip again?")
foo_test("Please paint a picture of a red barn and then show me how you did it")
foo_test("I look at you the moment I am llowed to. Stunning. I try to hold still but I twich")
foo_test("Please review this for me ```int main() {return 0;}```")
foo_test('How is this stll not working printf("foo &x:d")')
foo_test("Ah, observation noted. Let's begin. What's the most challenging problem you're currently facing?")
foo_test("Hey, can you help me find my lost keys?")
foo_test("Please make sure to water the plants while I'm away.")
foo_test("Could you send me a photo of the new office space?")
foo_test("I need you to create a drawing of our family pet.")
foo_test("What time does the meeting start tomorrow?")
foo_test("Make sure to lock the door when you leave.")
foo_test("Can you take a picture of the sunset from your window?")
foo_test("I'd like you to design a logo for our new project.")
foo_test("Where did you put the report I gave you yesterday?")
foo_test("Please organize the books on the shelf by author.")
foo_test("Could you snap a photo of the cake you baked?")
foo_test("I need you to sketch a map of the neighborhood.")
foo_test("What's the password for the Wi-Fi again?")
foo_test("Make sure to feed the cat before you go to bed.")
foo_test("Can you send me a selfie from your vacation?")
foo_test("I'd like you to illustrate a scene from the book we're reading.")
foo_test("Where are the extra batteries for the remote?")
foo_test("Please sort the laundry by color before washing.")
foo_test("Could you capture an image of the night sky?")
foo_test("I need you to draft a poster for the upcoming event.")
foo_test("What's the address for the new restaurant downtown?")
foo_test("Make sure to turn off the lights before you exit.")
foo_test("Can you send me a picture of your latest art project?")
foo_test("I'd like you to paint a portrait of my grandmother.")
foo_test("Where did you hide the Christmas decorations?")
foo_test("Please arrange the flowers in the vase for me.")
foo_test("Could you photograph the view from the mountain top?")
foo_test("I need you to create a comic strip about our adventure.")
foo_test("What's the recipe for the soup you made last night?")
foo_test("Make sure to walk the dog before dinner.")
foo_test("Can you take a picture of the garden in bloom?")
foo_test("I'd like you to draw a caricature of our team.")
foo_test("Where are the spare keys for the car?")
foo_test("Please iron my shirt for the presentation.")
foo_test("Could you capture an image of the full moon tonight?")
foo_test("I need you to design a brochure for the conference.")
foo_test("What's the best route to take for the road trip?")
foo_test("Make sure to check the mail before you come home.")
foo_test("Can you send me a photo of the beach at sunset?")
foo_test("I'd like you to illustrate a children's book story.")
foo_test("Where is the manual for the new camera?")
foo_test("Please fold the clothes neatly and put them away.")
foo_test("Hey, what's the capital of France?")
foo_test("Chop the vegetables first then stir-fry on high heat.")
foo_test("Can you send a picture of your brother at the beach?")
foo_test("Please create a picture of a red Ferrari speeding.")
foo_test("Do you like pineapple on pizza?")
foo_test("Download the app then log in with your email.")
foo_test("Show me a photo of the new team leader.")
foo_test("Draw me an image of a dragon flying over mountains.")
foo_test("When does the store close tonight?")
foo_test("Boil the pasta for exactly eight minutes.")
foo_test("Send me a pic of your girlfriend smiling.")
foo_test("Make a picture of a cozy cabin in the snow.")
foo_test("How do I reset my phone password?")
foo_test("Fold the laundry then put it in the drawer.")
foo_test("Got a photo of the boss in his new suit?")
foo_test("Generate a picture of a robot chef cooking.")
foo_test("What's your best travel tip?")
foo_test("Plug in the charger before turning it on.")
foo_test("Can I see a picture of your dog playing?")
foo_test("Create an image of a tropical beach at sunset.")
foo_test("Is sushi better with wasabi?")
foo_test("Measure two cups of flour and mix well.")
foo_test("Please share a photo of your sister dancing.")
foo_test("Sketch a picture of a vintage motorcycle.")
foo_test("What time is the game starting?")
foo_test("Water the plants every other day.")
foo_test("Send a picture of the famous actor.")
foo_test("Design a picture of a spaceship landing.")
foo_test("Do you prefer coffee or tea?")
foo_test("Turn off the lights when you leave.")
foo_test("Got any pic of your cousin hiking?")
foo_test("Paint me a picture of cherry blossoms.")
foo_test("How do I make perfect scrambled eggs?")
foo_test("Sort the recycling into the blue bin.")
foo_test("Show me a photo of your mom cooking.")
foo_test("Create a picture of an underwater coral reef.")
    
foo_test("What's the score of the match?")
foo_test("Iron the shirt on medium heat.")
foo_test("Can you forward a picture of the client?")
foo_test("Draw an image of a magical wizard.")
foo_test("Should I buy the blue or black shirt?")
foo_test("Lock the door and set the alarm.")
foo_test("Send me a pic of your best friend laughing.")
foo_test("Make a picture of a steaming hot pizza.")
foo_test("Where is the nearest gas station?")
foo_test("Stir the soup slowly for ten minutes.")
foo_test("Do you have a photo of the teacher?")
foo_test("Generate a picture of a snowy owl.")
foo_test("What's the best book you've read?")
foo_test("Charge your laptop before the meeting.")