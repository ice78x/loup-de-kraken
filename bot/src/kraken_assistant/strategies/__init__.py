from . import breakout_retest, news, rejection, trend

STRATEGIES = {
    breakout_retest.NAME: breakout_retest.find,
    rejection.NAME: rejection.find,
    trend.NAME: trend.find,
    news.NAME: news.find,
}
