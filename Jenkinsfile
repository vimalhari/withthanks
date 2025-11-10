pipeline {
    agent any

    environment {
        DOCKER_IMAGE = "withthanks-django"
        IMAGE_TAG = "1.0.0"
        CONTAINER_NAME = "withthanks-container"
        APP_PORT = "8000"
        DOCKER_HUB_USER = "rankraze"
        PATH = "$HOME/.local/bin:$PATH"  // 👈 Ensure user-level pip binaries are accessible
    }

    stages {

        stage('Checkout Code') {
            steps {
                echo "📂 Checking out source code..."
                git branch: 'main',
                    credentialsId: 'github-creds-1',
                    url: 'https://github.com/Rajachellan/WithThanks.git'
            }
        }

        stage('Setup Python Environment') {
            steps {
                sh '''
                echo "🐍 Checking Python & pip setup..."
                
                if ! command -v python3 &> /dev/null; then
                    echo "⚙️ Installing Python..."
                    apt-get update -y && apt-get install -y python3 python3-pip
                fi

                # Try reinstalling pip locally if not found
                if ! command -v pip3 &> /dev/null; then
                    echo "⚙️ Installing pip locally for Jenkins user..."
                    python3 -m ensurepip --user
                    python3 -m pip install --upgrade pip --user
                fi

                echo "✅ Python Version:"
                python3 --version
                echo "✅ pip Version:"
                python3 -m pip --version
                '''
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                echo "📦 Installing project dependencies..."
                python3 -m pip install --user --upgrade pip
                python3 -m pip install --user -r requirements.txt
                '''
            }
        }

        stage('Docker Login') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                    sh '''
                    echo "🔐 Logging in to Docker Hub..."
                    echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                    '''
                }
            }
        }

        stage('Build & Push Docker Image') {
            steps {
                sh '''
                echo "🐳 Building Docker image..."
                docker build -t $DOCKER_IMAGE:$IMAGE_TAG .

                echo "🏷️ Tagging image for Docker Hub..."
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:latest

                echo "🚀 Pushing image to Docker Hub..."
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:latest
                '''
            }
        }

        stage('Stop Old Container') {
            steps {
                sh '''
                echo "🛑 Stopping old container if running..."
                docker stop $CONTAINER_NAME || true
                docker rm $CONTAINER_NAME || true
                '''
            }
        }

        stage('Run New Container') {
            steps {
                sh '''
                echo "🚀 Running new Docker container..."
                docker run -d --name $CONTAINER_NAME \
                    --restart always \
                    -p $APP_PORT:8000 \
                    $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                '''
            }
        }
    }

    post {
        success {
            echo "✅ Deployment Successful! Application running on port $APP_PORT"
        }
        failure {
            echo "❌ Deployment Failed! Check Jenkins logs for details."
        }
    }
}
