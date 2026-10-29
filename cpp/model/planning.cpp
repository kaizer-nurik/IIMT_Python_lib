#include "model.hpp"

#include <ompl/base/ScopedState.h>
#include <ompl/base/spaces/RealVectorStateSpace.h>
#include <ompl/geometric/SimpleSetup.h>
#include <ompl/geometric/planners/rrt/RRTConnect.h>

#include <algorithm>
#include <cmath>
#include <sstream>
#include <stdexcept>

namespace iimt::model {
namespace ob = ompl::base;
namespace og = ompl::geometric;
namespace {
Positions positions(const ob::State *state, std::size_t size) {
  const auto *values = state->as<ob::RealVectorStateSpace::StateType>()->values;
  return Positions(values, values + size);
}

std::string contacts(const Check &check) {
  std::ostringstream text;
  for (const auto &pair : check.collisions)
    text << " " << pair.first << "/" << pair.second;
  return text.str();
}
} // namespace

std::vector<Positions> Model::plan(const Positions &start,
                                   const Positions &goal, double timeout,
                                   double resolution) const {
  if (!std::isfinite(timeout) || timeout <= 0 || timeout > 300)
    throw std::invalid_argument(
        "Planning timeout must be finite within (0, 300] seconds");
  if (!std::isfinite(resolution) || resolution <= 0 || resolution > 0.1)
    throw std::invalid_argument(
        "Collision resolution must be finite within (0, 0.1] radians");
  const auto start_check = check(start), goal_check = check(goal);
  if (!start_check.valid)
    throw std::invalid_argument("Invalid planning start:" +
                                contacts(start_check));
  if (!goal_check.valid)
    throw std::invalid_argument("Invalid planning goal:" +
                                contacts(goal_check));
  auto space = std::make_shared<ob::RealVectorStateSpace>(names_.size());
  ob::RealVectorBounds bounds(names_.size());
  for (std::size_t i = 0; i < names_.size(); ++i) {
    bounds.setLow(i, lower_[i]);
    bounds.setHigh(i, upper_[i]);
  }
  space->setBounds(bounds);
  og::SimpleSetup setup(space);
  setup.setStateValidityChecker([this](const ob::State *state) {
    return check(positions(state, names_.size())).valid;
  });
  // Euclidean segment length <= resolution also bounds every joint increment.
  setup.getSpaceInformation()->setStateValidityCheckingResolution(
      std::min(1., resolution / space->getMaximumExtent()));
  ob::ScopedState<> from(space), to(space);
  for (std::size_t i = 0; i < names_.size(); ++i) {
    from[i] = start[i];
    to[i] = goal[i];
  }
  setup.setStartAndGoalStates(from, to);
  auto planner = std::make_shared<og::RRTConnect>(setup.getSpaceInformation());
  planner->setRange(
      .2); // Avoid six-radian exploratory edges for short approaches.
  setup.setPlanner(planner);
  const auto solved = setup.solve(timeout);
  if (solved != ob::PlannerStatus::EXACT_SOLUTION)
    throw std::runtime_error("RRTConnect did not find an exact "
                             "collision-checked solution within timeout");
  // The common near-goal approach can be shortened with one checked connection.
  // Unlike a generic iterative simplifier, this adds only one motion
  // validation.
  if (setup.getSpaceInformation()->checkMotion(from.get(), to.get()))
    return {start, goal};
  const auto &path = setup.getSolutionPath();
  std::vector<Positions> result;
  result.push_back(start);
  for (std::size_t k = 1; k < path.getStateCount(); ++k) {
    const auto left = positions(path.getState(k - 1), names_.size());
    const auto right = positions(path.getState(k), names_.size());
    double largest = 0;
    for (std::size_t j = 0; j < names_.size(); ++j)
      largest = std::max(largest, std::abs(right[j] - left[j]));
    const std::size_t steps =
        std::max<std::size_t>(1, std::ceil(largest / resolution));
    for (std::size_t n = 1; n <= steps; ++n) {
      Positions q(names_.size());
      for (std::size_t j = 0; j < q.size(); ++j)
        q[j] = left[j] + (right[j] - left[j]) * static_cast<double>(n) / steps;
      if (!check(q).valid)
        throw std::runtime_error(
            "RRTConnect post-validation detected a colliding sample");
    }
    // Checking samples are not stop waypoints in the returned geometric path.
    result.push_back(right);
  }
  // Preserve exact user endpoints; never return an approximate OMPL goal.
  result.front() = start;
  result.back() = goal;
  return result;
}
} // namespace iimt::model
