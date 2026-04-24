from datetime import datetime

import pytest
from analysis_bot.models.content import News, Podcast, Report
from analysis_bot.models.stock import StockData
from analysis_bot.models.subscriber import Subscriber
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel


@pytest.fixture
def in_memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture
def db_session(in_memory_db):
    with Session(in_memory_db) as session:
        yield session


class TestStockData:
    def test_create_stock_data(self, db_session):
        stock = StockData(
            ticker="2330.TW", name="台積電", sector="Technology", price=550.0, tag="favorite"
        )
        db_session.add(stock)
        db_session.commit()
        db_session.refresh(stock)

        assert stock.id is not None
        assert stock.ticker == "2330.TW"
        assert stock.name == "台積電"
        assert stock.sector == "Technology"
        assert stock.price == 550.0
        assert stock.tag == "favorite"

    def test_stock_data_default_values(self, db_session):
        stock = StockData(ticker="2317.TW")
        db_session.add(stock)
        db_session.commit()
        db_session.refresh(stock)

        assert stock.name is None
        assert stock.tag is None
        assert stock.sector is None
        assert stock.price is None
        assert isinstance(stock.last_analyzed, datetime)

    def test_unique_ticker_constraint(self, db_session):
        stock1 = StockData(ticker="2330.TW")
        stock2 = StockData(ticker="2330.TW")

        db_session.add(stock1)
        db_session.commit()

        db_session.add(stock2)
        with pytest.raises(Exception):
            db_session.commit()


class TestSubscriber:
    def test_create_subscriber(self, db_session):
        subscriber = Subscriber(chat_id=123456789, news_enabled=True)
        db_session.add(subscriber)
        db_session.commit()
        db_session.refresh(subscriber)

        assert subscriber.id is not None
        assert subscriber.chat_id == 123456789
        assert subscriber.news_enabled is True
        assert isinstance(subscriber.created_at, datetime)

    def test_subscriber_default_news_enabled(self, db_session):
        subscriber = Subscriber(chat_id=123456789)
        db_session.add(subscriber)
        db_session.commit()
        db_session.refresh(subscriber)

        assert subscriber.news_enabled is False

    def test_unique_chat_id_constraint(self, db_session):
        sub1 = Subscriber(chat_id=123456789)
        sub2 = Subscriber(chat_id=123456789)

        db_session.add(sub1)
        db_session.commit()

        db_session.add(sub2)
        with pytest.raises(Exception):
            db_session.commit()


class TestNews:
    def test_create_news(self, db_session):
        news = News(
            title="Test News Article", link="https://example.com/news/1", source="Test Source"
        )
        db_session.add(news)
        db_session.commit()
        db_session.refresh(news)

        assert news.id is not None
        assert news.title == "Test News Article"
        assert news.link == "https://example.com/news/1"
        assert news.source == "Test Source"
        assert isinstance(news.created_at, datetime)

    def test_news_default_source(self, db_session):
        news = News(title="Test News", link="https://example.com/news/2")
        db_session.add(news)
        db_session.commit()
        db_session.refresh(news)

        assert news.source is None

    def test_unique_link_constraint(self, db_session):
        news1 = News(title="News 1", link="https://example.com/news/3")
        news2 = News(title="News 2", link="https://example.com/news/3")

        db_session.add(news1)
        db_session.commit()

        db_session.add(news2)
        with pytest.raises(Exception):
            db_session.commit()


class TestReport:
    def test_create_report(self, db_session):
        report = Report(title="Analysis Report", link="https://example.com/report/1")
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        assert report.id is not None
        assert report.title == "Analysis Report"
        assert report.link == "https://example.com/report/1"
        assert isinstance(report.created_at, datetime)


class TestPodcast:
    def test_create_podcast(self, db_session):
        podcast = Podcast(
            host="Test Host", title="Podcast Episode", url="https://example.com/podcast/1"
        )
        db_session.add(podcast)
        db_session.commit()
        db_session.refresh(podcast)

        assert podcast.id is not None
        assert podcast.host == "Test Host"
        assert podcast.title == "Podcast Episode"
        assert podcast.url == "https://example.com/podcast/1"
        assert isinstance(podcast.created_at, datetime)

    def test_podcast_default_url(self, db_session):
        podcast = Podcast(host="Test Host", title="Podcast Episode 2")
        db_session.add(podcast)
        db_session.commit()
        db_session.refresh(podcast)

        assert podcast.url is None
