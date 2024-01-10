from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello, World!'

if __name__ == '__main__':
    app.run(debug=True) # useful for development, remember to turn off debug mode in production as it can expose sensitive information.
